/* Upload sweep: drive the real upload panel in the real browser with all 26 documents in
 * testdata/uploads/, and report what the screen actually said about each one.
 *
 * This is not a unit test of the extractor -- the point is the screen. For every document
 * it reads back the panel's own rendered text, so a cohort that recovers nothing is
 * recorded together with the sentence a renter would be looking at.
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
await page.locator("#start-demo").click();
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
  await page.waitForFunction(
    () => {
      const host = document.querySelector("#upload-result-host");
      return host && host.textContent.trim().length > 0 &&
             !/Reading the document/.test(host.textContent);
    },
    { timeout: 60000 },
  ).catch(() => {});
  await page.waitForTimeout(150);

  const info = await page.evaluate(() => {
    const host = document.querySelector("#upload-result-host");
    const text = host ? host.innerText : "";
    const headings = Array.from(host ? host.querySelectorAll("h3") : []).map((n) => n.textContent.trim());
    const kv = {};
    const dl = host ? host.querySelector("dl.kv") : null;
    if (dl) {
      const dts = Array.from(dl.querySelectorAll("dt"));
      const dds = Array.from(dl.querySelectorAll("dd"));
      dts.forEach((dt, i) => { kv[dt.textContent.trim()] = (dds[i] || {}).textContent?.trim() || ""; });
    }
    return {
      text, headings, kv,
      rows: host ? host.querySelectorAll("table tbody tr").length : 0,
      hasImage: Boolean(host && host.querySelector(".page-frame img")),
      isError: Boolean(host && host.querySelector(".callout--stop")),
      readNothing: /could not confidently read any field/i.test(text),
    };
  });

  const shot = shotFor[doc.file_name];
  if (wantShots && shot) {
    await page.locator("#upload-body").screenshot({ path: join(SHOTS, `${shot}.png`) });
  }

  rows.push({
    file: doc.file_name,
    cohort: doc.cohort === "pack_form" ? (doc.rasterized ? "pack_form_scan" : "pack_form_text") : doc.cohort,
    outcome: info.isError ? "REJECTED" : info.readNothing ? "READ-NOTHING" : "FIELDS-SHOWN",
    heading: info.headings[0] || "",
    located: info.kv["Fields we could read"] || "",
    readVia: info.kv["How we read it"] || "",
    tableRows: info.rows,
    image: info.hasImage,
    note: info.isError ? info.text.split("\n").slice(1).join(" ").slice(0, 160) : "",
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
