/* Photograph the two defect sequences, so "fixed" is something a person can look at
 * rather than something a log claims.
 *
 * The same script runs against the pre-fix build and the fixed one, taking the same
 * shots in the same order at the same size. Anything that differs between the two sets
 * is the change; anything that does not, is not.
 *
 *   node ui/tools/defect-shots.mjs http://127.0.0.1:8077 <output-dir> <label>
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:8000";
const outDir = process.argv[3] || "shots";
const label = process.argv[4] || "run";
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
let n = 0;
const shot = async (name) => {
  n += 1;
  const file = join(outDir, `${label}-${String(n).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log("shot", file);
};

const report = () => page.evaluate(() => window.REALDOOR_LAST_REPORT);
const next = async () => { await page.locator("#step-next").click(); await page.waitForTimeout(200); };
const say = (msg) => console.log("   " + msg);

await page.goto(`${base}/?live`);
await page.waitForFunction(() => document.querySelectorAll("#documents-body table").length > 0, { timeout: 20000 });
await page.selectOption("#household-select", "HH-004");
await page.waitForFunction(() => window.REALDOOR_LAST_REPORT &&
  window.REALDOOR_LAST_REPORT.household_id === "HH-004", { timeout: 15000 });
await page.locator("#start-demo").click();
await page.waitForTimeout(250);
await next();   // step 2

// ── defect 1 ────────────────────────────────────────────────────────────────────
async function correct(doc, field, value) {
  await page.selectOption("#correct-doc", doc);
  await page.selectOption("#correct-field", field);
  await page.fill("#correct-value", String(value));
  await page.locator("#correct-apply").click();
  await page.waitForTimeout(800);
}
const payOf = async () => {
  const r = await report();
  const d = (r.documents || []).find((x) => x.document_id === "HH-004-D02");
  const f = (d ? d.fields : []).find((x) => x.field === "gross_pay");
  return f ? `${f.value} (${f.evidence_kind})` : "missing";
};
const codesOf = async () =>
  ((await report()).review_reasons || []).map((r) => r.code).join(", ") || "none";

await correct("HH-004-D02", "gross_pay", 2280);
await shot("d1-step1-corrected-2280");
say(`after correcting D02 gross_pay=2280 -> ${await payOf()} | ${await codesOf()}`);

const undo = page.locator("#correct-undo").or(page.getByRole("button", { name: "Undo correction" }));
await undo.first().click();
await page.waitForTimeout(900);
await shot("d1-step2-undone");
say(`after undo -> ${await payOf()} | ${await codesOf()}`);

await correct("HH-004-D01", "household_size", 2);
await shot("d1-step3-corrected-something-else");
say(`after correcting D01 household_size=2 -> D02 gross_pay is ${await payOf()}`);
say(`open items now: ${await codesOf()}`);

// ── defect 2 ────────────────────────────────────────────────────────────────────
await next(); await next(); await next(); await next();   // steps 3,4,5,6
await shot("d2-step0-packet-screen");
const hasJourneyDelete = await page.locator("#packet-delete-session").count();
say(`delete control inside the six steps: ${hasJourneyDelete ? "yes" : "NO"}`);

const health = async () => (await (await fetch(`${base}/api/health`)).json()).active_sessions;
const before = await health();

if (hasJourneyDelete) {
  await page.locator("#packet-delete-session").click();
} else {
  // pre-fix build: the only delete lives on the judge-facing page
  await page.locator("#go-how").click();
  await page.waitForTimeout(200);
  await page.getByRole("button", { name: "Delete session data now" }).click();
}
await page.waitForTimeout(1500);
await shot("d2-step1-after-delete");

// "go back to where you were" -- the move the audit made
if (!hasJourneyDelete) {
  await page.locator("#nav-how button").first().click();
  await page.waitForTimeout(1200);
} else {
  await page.locator("#step-back").click();
  await page.waitForTimeout(300);
  await page.locator("#step-back").click();
  await page.waitForTimeout(1200);
}
await shot("d2-step2-back-where-you-were");
const held = await report();
say(`report still on the page after deleting: ${held ? held.household_id : "none"}`);
say(`active sessions ${before} -> ${await health()}`);

// and the packet, which the screen said there was nothing left to build
await page.evaluate(() => {
  const btn = document.getElementById("step-next");
  return btn ? null : null;
});
for (let i = 0; i < 4; i += 1) {
  if (await page.locator("#packet-download").count()) break;
  if (!(await page.locator("#step-next").count())) break;
  await next();
}
const downloadable = await page.locator("#packet-download").count();
say(`packet download button present after deletion: ${downloadable ? "YES" : "no"}`);
if (downloadable) {
  const dl = page.waitForEvent("download", { timeout: 8000 }).catch(() => null);
  await page.locator("#packet-download").click();
  await page.waitForTimeout(1200);
  const file = await dl;
  say(`packet download after deletion: ${file ? "SUCCEEDED -> " + file.suggestedFilename() : "failed"}`);
}
await shot("d2-step3-packet-attempt");
say(`active sessions at the end: ${await health()}`);

await browser.close();
