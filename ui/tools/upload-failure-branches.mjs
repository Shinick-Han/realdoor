/* upload-failure-branches.mjs — which failure gets which screen, and what the screen
 * is allowed to touch.
 *
 * The upload panel used to have two states for every possible refusal: "the page did
 * not announce itself" (open the type selector, explain, ask) and a generic card that
 * said "We did not read that file". A rate-limit pause landed in that pair too, so a
 * renter whose file was never even opened was shown a control about document types and
 * a sentence blaming the page. Wrong cause, wrong action.
 *
 * The branch now keys off the code the *server* reported, so this harness feeds the
 * panel one real server payload per branch — through route interception, so the shapes
 * are exactly what api/upload.py and api/limits.py emit — and asserts three things each
 * time: which card appeared, whether the type selector moved, and whether the
 * "did not announce itself" sentence is on screen.
 *
 * The selector assertion is the point. It is checked in both starting positions,
 * because "do not touch it" means do not open a closed one AND do not close an open one.
 *
 * Start the server first:  python -m uvicorn api.app:app --port 8099
 *   node ui/tools/upload-failure-branches.mjs [http://127.0.0.1:8099]
 */
import { chromium } from "playwright";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const base = process.argv[2] || "http://127.0.0.1:8099";
const FILE = join(ROOT, "testdata", "uploads", "up_003_pay_stub_john_doe.pdf");

/* The four server payloads, copied in shape from what the endpoints actually send. */
const REJECT = (code, detail) => ({
  status: 400, contentType: "application/json",
  body: JSON.stringify({ detail: { code, detail } }),
});
const PAUSE = (seconds) => ({
  status: 429, contentType: "application/json",
  headers: { "Retry-After": String(seconds) },
  body: JSON.stringify({
    error: "too_many_requests",
    detail: "This copy is not handling more uploads from your connection right now. It is a " +
            "free public demo running as one process, and the cap is there so one client " +
            "cannot take the whole thing away from everyone else. Nothing about your session " +
            "was changed or lost. Wait " + seconds + " seconds and repeat what you were doing.",
    retry_after_seconds: seconds,
  }),
});

const NOT_ANNOUNCED = REJECT(
  "type_not_announced",
  "The page did not announce what it is: nothing printed at the top of it matches a kind of " +
  "document we know. Choose the kind of document below and we will read it that way.");

let passed = 0, failed = 0;
function check(name, ok, got) {
  if (ok) { passed++; console.log(`  ok    ${name}`); }
  else { failed++; console.log(`  FAIL  ${name}${got === undefined ? "" : ` — got ${JSON.stringify(got)}`}`); }
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();

let nextResponse = null;
await page.route("**/api/upload", async (route) => {
  if (route.request().method() !== "POST") return route.continue();
  if (!nextResponse) return route.continue();
  const r = nextResponse;
  nextResponse = null;
  await route.fulfill(r);
});

await page.goto(`${base}/?live`);
await page.waitForFunction(() => document.querySelector("#upload-type") !== null, { timeout: 30000 });

async function panel() {
  return page.evaluate(() => {
    const d = document.querySelector("#upload-type-details");
    const host = document.querySelector("#upload-result-host");
    const note = document.querySelector("#upload-ask-note-host");
    const heading = document.querySelector("#upload-result-heading");
    return {
      selectorOpen: d ? d.open : null,
      askNoteShown: note ? !note.hidden && note.textContent.trim().length > 0 : false,
      heading: heading ? heading.textContent.trim() : "",
      text: host ? host.textContent.replace(/\s+/g, " ").trim() : "",
      hasRetry: Boolean(document.querySelector("#upload-pause-retry")),
      retryDisabled: document.querySelector("#upload-pause-retry")
        ? document.querySelector("#upload-pause-retry").disabled : null,
      readyLine: document.querySelector("#upload-pause-ready")
        ? document.querySelector("#upload-pause-ready").textContent.trim() : "",
    };
  });
}

async function setSelector(open) {
  await page.evaluate((want) => {
    const d = document.querySelector("#upload-type-details");
    if (d && d.open !== want) d.open = want;
  }, open);
  await page.waitForTimeout(80);
}

async function send(response) {
  nextResponse = response;
  await page.locator("#upload-file").setInputFiles(FILE);
  await page.locator(".upload-form button[type=submit]").click();
  await page.waitForFunction(() => {
    const h = document.querySelector("#upload-result-host");
    const note = document.querySelector("#upload-ask-note-host");
    const busy = h && h.textContent.includes("Reading the text on the page");
    return !busy && ((h && h.textContent.trim().length > 0) || (note && !note.hidden));
  }, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(120);
  return panel();
}

/* ── 1. the designed fallback: the page did not announce itself ─────────────────── */
console.log("\ntype_not_announced — the selector opens, and says why");
await setSelector(false);
{
  const p = await send(NOT_ANNOUNCED);
  check("the type selector opens", p.selectorOpen === true, p.selectorOpen);
  check("the server's sentence is beside it", p.askNoteShown === true, p.askNoteShown);
  check("no refusal card about the file", !p.text.includes("We did not read that file"), p.heading);
}

/* ── 2. the pause, arriving right after the fallback ────────────────────────────── */
console.log("\ntoo_many_requests, after a fallback — the sentence is taken back, the selector is not");
{
  const p = await send(PAUSE(7));
  check("the pause card, not the refusal card",
        p.heading === "Nothing is wrong with your file", p.heading);
  check("the 'did not announce itself' sentence is gone", p.askNoteShown === false, p.askNoteShown);
  check("the selector is left where the renter had it (open)", p.selectorOpen === true, p.selectorOpen);
  check("the server's own wait is on screen", /Wait 7 seconds/.test(p.text), p.text.slice(0, 80));
  check("a retry affordance exists", p.hasRetry === true, p.hasRetry);
  check("it waits out the server's pause first", p.retryDisabled === true, p.retryDisabled);
  check("and says how long", /Ready to try again in \d+ seconds\./.test(p.readyLine), p.readyLine);
  check("it does not say the file was the problem",
        !/could not|did not read|not a PDF/i.test(p.text), p.text.slice(0, 120));
}

/* ── 3. the pause with the selector closed — it must not open ───────────────────── */
console.log("\ntoo_many_requests, selector closed — it stays closed");
await setSelector(false);
{
  const p = await send(PAUSE(3));
  check("the selector did not move", p.selectorOpen === false, p.selectorOpen);
  check("still the pause card", p.heading === "Nothing is wrong with your file", p.heading);
  check("no ask note", p.askNoteShown === false, p.askNoteShown);
}

/* ── 4. everything else: about the file, and only about the file ────────────────── */
const OTHERS = [
  ["file_too_large", "That upload is 12.4 MB. The limit is 10 MB, because an uploaded document is held in memory for this session only and never written to disk."],
  ["empty_file", "That file is empty."],
  ["not_a_pdf", "That file is not a PDF, PNG or JPG. Its first bytes are not one of those headers, whatever its name or type says."],
  ["unreadable_pdf", "We could not open that PDF (PDFSyntaxError). It may be damaged or password-protected."],
  ["session_upload_limit", "This session already holds 6 uploaded documents, and they all stay in this session's memory. That is the ceiling."],
];
for (const open of [false, true]) {
  console.log(`\nthe file's own refusals — selector starts ${open ? "open" : "closed"}`);
  for (const [code, detail] of OTHERS) {
    await setSelector(open);
    const p = await send(REJECT(code, detail));
    check(`${code}: its own message, kept whole`, p.text.includes(detail.slice(0, 40)), p.text.slice(0, 90));
    check(`${code}: the refusal card`, p.heading === "We did not read that file", p.heading);
    check(`${code}: the selector did not move`, p.selectorOpen === open, p.selectorOpen);
    check(`${code}: no 'did not announce itself' sentence`, p.askNoteShown === false, p.askNoteShown);
    check(`${code}: not dressed as a pause`, !p.hasRetry, p.hasRetry);
  }
}

/* ── 5. the countdown actually ends, and the button comes back ──────────────────── */
console.log("\nthe pause ends by itself");
await setSelector(false);
{
  await send(PAUSE(2));
  await page.waitForTimeout(2600);
  const p = await panel();
  check("the retry button is usable once the wait is over", p.retryDisabled === false, p.retryDisabled);
  check("and says so", p.readyLine === "You can try again now.", p.readyLine);
}

console.log(`\n${passed}/${passed + failed} checks passed`);
await browser.close();
process.exit(failed === 0 ? 0 : 1);
