/* Upload sweep: drive the real upload panel in the real browser with all 26 documents in
 * testdata/uploads/, and report what the screen actually said about each one.
 *
 * This is not a unit test of the extractor -- the point is the screen. For every document
 * it reads back what the screen shows, so a cohort that recovers nothing is recorded
 * together with the sentence a renter would be looking at.
 *
 * A successful upload no longer renders a read-only preview: it lands DIRECTLY in the
 * editable uploads-household view (#documents-body). So for a document that reads, this
 * sweep reads back that view — its heading, its field rows, the relocated banner/notes —
 * and only falls back to the upload panel (#upload-result-host) for the states that stay
 * there: the refusal card and the rate-limit pause.
 *
 * Start the server first:  python -m uvicorn api.app:app --port 8077
 *   node ui/tools/upload-sweep.mjs [http://127.0.0.1:8077] [--shots]
 */
import { chromium } from "playwright";
import { readFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, "..", "..");
const base = process.argv[2] && !process.argv[2].startsWith("--") ? process.argv[2] : "http://127.0.0.1:8077";
const wantShots = process.argv.includes("--shots");
const SHOTS = join(ROOT, "ui", "screenshots-upload");
if (wantShots) mkdirSync(SHOTS, { recursive: true });

const manifest = JSON.parse(readFileSync(join(ROOT, "testdata", "uploads_manifest.json"), "utf8"));

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();

await page.goto(`${base}/?live`);
await page.waitForFunction(() => document.querySelector("#upload-type") !== null, { timeout: 20000 });
await page.waitForTimeout(200);

// Documents chosen for screenshots: one per cohort, plus the empty-result case.
const shotFor = {
  "up_003_pay_stub_john_doe.pdf": "01-pack-form-text",
  "up_006_pay_stub_sam_poe_scan.pdf": "02-pack-form-scan-ocr",
  "up_016_pay_stub_wording_total_earnings.pdf": "03-label-wording-read-nothing",
  "up_019_pay_stub_labels_10pt.pdf": "04-typography-10pt",
  "up_023_pay_stub_side_by_side.pdf": "05-layout-read-nothing",
  "up_004_pay_stub_john_doe_mismatch.pdf": "06-internally-inconsistent",
};

const rows = [];
for (const doc of manifest.documents) {
  const file = join(ROOT, "testdata", "uploads", doc.file_name);
  // A fresh page load mints a fresh session (the client holds its id in memory only), so
  // each document is measured on an empty desk and the 6-upload session cap is never a
  // factor across the 26-document sweep.
  await page.goto(`${base}/?live`);
  await page.waitForFunction(() => document.querySelector("#upload-type") !== null, { timeout: 20000 });
  // The live uploadTypes fetch re-renders this panel once it lands; wait for the option we
  // want (or, for a genuinely unsupported kind, settle and let the select prove it absent),
  // so a mid-select re-render cannot silently reset the chosen value.
  await page.waitForFunction((want) => {
    const sel = document.querySelector("#upload-type");
    return sel && Array.from(sel.options).some((o) => o.value === want);
  }, doc.document_type, { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(300);
  // The manual type select lives inside the "Choose the kind yourself" disclosure, which is
  // closed by default; open it so the select is interactable (the empty default would
  // otherwise read the kind off the page — not what this per-type sweep measures).
  await page.evaluate(() => {
    const d = document.querySelector("#upload-type-details");
    if (d && !d.open) d.open = true;
  });
  await page.locator("#upload-type").selectOption(doc.document_type).catch(() => {});
  const typeAccepted = await page.locator("#upload-type").inputValue() === doc.document_type;
  if (!typeAccepted) {
    rows.push({
      file: doc.file_name, cohort: doc.cohort, outcome: "TYPE-NOT-OFFERED",
      heading: "", located: "", note: `the panel offers no "${doc.document_type}" option`,
    });
    continue;
  }
  await page.locator("#upload-file").setInputFiles(file);
  await page.locator(".upload-form button[type=submit]").click();
  // Resolve to one of three end states: the editable view landed (success), the panel's
  // refusal card, or the panel's pause card. Whichever first, the busy line must be gone.
  await page.waitForFunction(
    () => {
      const panel = document.querySelector("#upload-result-host");
      const landed = document.querySelectorAll("#documents-body table").length > 0;
      const panelText = panel ? panel.textContent : "";
      const busy = /Reading the text on the page/.test(panelText);
      const panelCard = Boolean(panel && (panel.querySelector(".callout--stop") ||
        panel.querySelector("#upload-pause-retry")));
      return landed || (!busy && panelCard);
    },
    { timeout: 60000 },
  ).catch(() => {});
  await page.waitForTimeout(1600); // let any staged reveal finish before reading rows

  const info = await page.evaluate(() => {
    const panel = document.querySelector("#upload-result-host");
    const isError = Boolean(panel && panel.querySelector(".callout--stop"));
    const isPause = Boolean(panel && panel.querySelector("#upload-pause-retry"));
    if (isError || isPause) {
      return { isError, isPause, text: panel.innerText,
        heading: (panel.querySelector("h3") || {}).textContent?.trim() || "",
        rows: 0, hasImage: false, readNothing: false, located: "" };
    }
    // landed in the editable view
    const body = document.querySelector("#documents-body");
    const text = body ? body.innerText : "";
    const heading = (body && body.querySelector("#doc-detail-heading") || {}).textContent?.trim() || "";
    const kv = {};
    const dl = body ? body.querySelector("dl.kv") : null;
    if (dl) {
      const dts = Array.from(dl.querySelectorAll("dt"));
      const dds = Array.from(dl.querySelectorAll("dd"));
      dts.forEach((dt, i) => { kv[dt.textContent.trim()] = (dds[i] || {}).textContent?.trim() || ""; });
    }
    return {
      isError: false, isPause: false, text, heading, kv,
      rows: body ? body.querySelectorAll("table tbody tr").length : 0,
      hasImage: Boolean(body && body.querySelector(".page-frame img")),
      readNothing: /could not confidently read any field/i.test(text),
      located: kv["Read via"] || "",
    };
  });

  const shot = shotFor[doc.file_name];
  if (wantShots && shot) {
    await page.locator("#main").screenshot({ path: join(SHOTS, `${shot}.png`) });
  }

  rows.push({
    file: doc.file_name,
    cohort: doc.cohort === "pack_form" ? (doc.rasterized ? "pack_form_scan" : "pack_form_text") : doc.cohort,
    outcome: info.isError ? "REJECTED" : info.isPause ? "PAUSED"
      : info.readNothing ? "READ-NOTHING" : "FIELDS-SHOWN",
    heading: info.heading || "",
    located: String(info.rows || ""),
    readVia: info.isError || info.isPause ? "" : (info.hasImage ? "image shown" : "no image"),
    tableRows: info.rows,
    image: info.hasImage,
    note: (info.isError || info.isPause) ? info.text.split("\n").slice(1).join(" ").slice(0, 160) : "",
  });
}

console.log("");
console.log(
  "file".padEnd(50) + "cohort".padEnd(17) + "outcome".padEnd(15) +
  "located".padEnd(10) + "img  read via",
);
for (const r of rows) {
  console.log(
    r.file.padEnd(50) + r.cohort.padEnd(17) + r.outcome.padEnd(15) +
    String(r.located).padEnd(10) + (r.image ? "yes  " : "no   ") + (r.readVia || r.note),
  );
}

const byOutcome = {};
for (const r of rows) byOutcome[r.outcome] = (byOutcome[r.outcome] || 0) + 1;
console.log("\n" + JSON.stringify(byOutcome));
if (wantShots) console.log("screenshots: " + SHOTS);

await browser.close();
