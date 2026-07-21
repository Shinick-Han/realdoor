/* axe-upload-failures.mjs — accessibility of the upload panel's three failure states.
 *
 * ui/tools/axe-scan.mjs walks the flow over file://, where the upload panel is inert:
 * reading a PDF needs the server, so the states this file measures are unreachable
 * there and were never scanned. These three are now distinct screens with distinct
 * causes — the type-selector fallback, the rate-limit pause with its countdown and its
 * retry button, and the file's own refusal — so each is scanned on its own.
 *
 * The refusals are injected by route interception, in the exact shapes api/upload.py
 * and api/limits.py send, so the states are the real ones and no rate limit has to be
 * spent to reach them.
 *
 * Start the server first:  python -m uvicorn api.app:app --port 8099
 *   node ui/tools/axe-upload-failures.mjs [http://127.0.0.1:8099]
 */
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, "..", "..");
const base = process.argv[2] || "http://127.0.0.1:8099";
const axeSource = readFileSync(resolve(here, "node_modules", "axe-core", "axe.min.js"), "utf8");
const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const FILE = join(ROOT, "testdata", "uploads", "up_003_pay_stub_john_doe.pdf");

const STATES = [
  {
    id: "type-not-announced",
    response: {
      status: 400, contentType: "application/json",
      body: JSON.stringify({ detail: { code: "type_not_announced",
        detail: "The page did not announce what it is: nothing printed at the top of it " +
                "matches a kind of document we know. Choose the kind of document below " +
                "and we will read it that way." } }),
    },
  },
  {
    id: "rate-limit-pause",
    response: {
      status: 429, contentType: "application/json",
      headers: { "Retry-After": "9" },
      body: JSON.stringify({ error: "too_many_requests", retry_after_seconds: 9,
        detail: "This copy is not handling more uploads from your connection right now. " +
                "It is a free public demo running as one process, and the cap is there so " +
                "one client cannot take the whole thing away from everyone else. Nothing " +
                "about your session was changed or lost. Wait 9 seconds and repeat what " +
                "you were doing." }),
    },
  },
  {
    id: "file-refused",
    response: {
      status: 400, contentType: "application/json",
      body: JSON.stringify({ detail: { code: "not_a_pdf",
        detail: "That file is not a PDF, PNG or JPG. Its first bytes are not one of those " +
                "headers, whatever its name or type says." } }),
    },
  },
];

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();

let nextResponse = null;
await page.route("**/api/upload", async (route) => {
  if (route.request().method() !== "POST" || !nextResponse) return route.continue();
  const r = nextResponse;
  nextResponse = null;
  await route.fulfill(r);
});

await page.goto(`${base}/?live`);
await page.waitForFunction(() => document.querySelector("#upload-type") !== null, { timeout: 30000 });

let total = 0;
for (const state of STATES) {
  nextResponse = state.response;
  await page.locator("#upload-file").setInputFiles(FILE);
  await page.locator(".upload-form button[type=submit]").click();
  await page.waitForFunction(() => {
    const h = document.querySelector("#upload-result-host");
    const note = document.querySelector("#upload-ask-note-host");
    const busy = h && h.textContent.includes("Reading the text on the page");
    return !busy && ((h && h.textContent.trim().length > 0) || (note && !note.hidden));
  }, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(200);

  await page.evaluate(axeSource);
  const run = await page.evaluate(async (tags) => {
    const outcome = await window.axe.run(document, {
      runOnly: { type: "tag", values: tags },
      resultTypes: ["violations", "incomplete"],
    });
    return {
      violations: outcome.violations.map((v) => ({
        id: v.id, impact: v.impact, help: v.help,
        nodes: v.nodes.map((n) => ({ target: n.target, failureSummary: n.failureSummary })),
      })),
      incomplete: outcome.incomplete.length,
    };
  }, WCAG_TAGS);

  total += run.violations.length;
  console.log(`${state.id.padEnd(20)} violations=${String(run.violations.length).padStart(2)}  ` +
              `incomplete=${String(run.incomplete).padStart(2)}`);
  for (const v of run.violations) {
    console.log(`    - [${v.impact}] ${v.id}: ${v.help}`);
    for (const n of v.nodes) console.log(`        ${n.target}`);
  }
}

console.log(`\ntotal violations: ${total} across ${STATES.length} upload failure states`);
await browser.close();
process.exit(total === 0 ? 0 : 1);
