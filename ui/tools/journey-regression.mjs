/* Two sequences that a person takes and a checker never did.
 *
 * Both defects this file guards were reachable in three clicks and survived every other
 * harness, because each harness pressed each control once and in isolation. Neither bug
 * lives in a control; both live in what a control leaves behind for the next one. So this
 * script does not check controls, it walks orders:
 *
 *   1. Correct a field, undo it, then correct a different field.
 *      The undone value used to come back in the report, adding a second open item and
 *      flipping the headline to "was NOT used" for a correction that no longer existed.
 *      Undo was a client-side rewind; the server session still held the corrected value.
 *
 *   2. Delete the session, then carry on using the page.
 *      The page used to mint a fresh session on the next request and the server re-loaded
 *      the pack into it, so the household reappeared and the packet still downloaded --
 *      seconds after a screen that said requests which follow return 404.
 *
 * Live mode only: both defects are about state held on the server, which the bundled
 * fixtures do not have.
 *
 *   node ui/tools/journey-regression.mjs [http://127.0.0.1:8077]
 */
import { chromium } from "playwright";

const base = process.argv[2] || "http://127.0.0.1:8077";
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const page = await context.newPage();

const checks = [];
function record(name, ok, detail) {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}

const activeSessions = async () =>
  (await (await fetch(`${base}/api/health`)).json()).active_sessions;

/** The report the page is holding right now, through the read-only window app.js exposes. */
const shownReport = () => page.evaluate(() => window.REALDOOR_LAST_REPORT);

const next = async () => { await page.locator("#step-next").click(); await page.waitForTimeout(150); };

async function loadHousehold(id) {
  await page.selectOption("#household-select", id);
  await page.waitForFunction(
    (want) => window.REALDOOR_LAST_REPORT && window.REALDOOR_LAST_REPORT.household_id === want,
    id, { timeout: 15000 });
}

async function applyCorrection(documentId, field, value) {
  await page.selectOption("#correct-doc", documentId);
  await page.selectOption("#correct-field", field);
  await page.fill("#correct-value", String(value));
  await page.locator("#correct-apply").click();
  await page.waitForTimeout(700);
}

function fieldValue(report, documentId, field) {
  const doc = (report.documents || []).find((d) => d.document_id === documentId);
  const found = (doc ? doc.fields : []).find((f) => f.field === field);
  return found ? found : null;
}
const codes = (report) => (report.review_reasons || []).map((r) => r.code);

await page.goto(`${base}/?live`);
await page.waitForFunction(() => document.querySelectorAll("#documents-body table").length > 0,
  { timeout: 20000 });

/* ── sequence 1: correct, undo, correct something else ────────────────────────── */
await loadHousehold("HH-004");
// The walkthrough opens on step 1; there is no landing screen in front of it to leave.
await page.waitForTimeout(200);
await next();   // step 2

const baseline = await shownReport();
const extractedPay = fieldValue(baseline, "HH-004-D02", "gross_pay").value;

await applyCorrection("HH-004-D02", "gross_pay", 2280);
const corrected = await shownReport();
record("Sequence 1a — the correction is applied and visible in the report",
  fieldValue(corrected, "HH-004-D02", "gross_pay").value === 2280,
  `gross_pay ${extractedPay} -> ${fieldValue(corrected, "HH-004-D02", "gross_pay").value}`);

/* Found by role as well as by id, so this script can be pointed at a build that predates
 * the id and still produce a FAIL line rather than a crash. A regression check that dies
 * on the broken build is not reporting the regression, it is just dying. */
await page.locator("#correct-undo")
  .or(page.getByRole("button", { name: "Undo correction" })).first().click();
await page.waitForTimeout(900);
const undone = await shownReport();
const undoneField = fieldValue(undone, "HH-004-D02", "gross_pay");
record("Sequence 1b — undo puts the extracted value back, as the button says it does",
  undoneField.value === extractedPay && undoneField.evidence_kind === "extracted",
  `gross_pay = ${undoneField.value} (${undoneField.evidence_kind})`);
record("Sequence 1c — undo also clears what the correction had added to the report",
  !codes(undone).includes("RENTER_CORRECTION_NOT_USED"),
  `open items: ${codes(undone).length}`);

await applyCorrection("HH-004-D01", "household_size", 2);
const after = await shownReport();
const revived = fieldValue(after, "HH-004-D02", "gross_pay");
const kept = fieldValue(after, "HH-004-D01", "household_size");
record("Sequence 1d — the undone correction does not come back on the next correction",
  revived.value === extractedPay && revived.evidence_kind === "extracted" &&
  !codes(after).includes("RENTER_CORRECTION_NOT_USED"),
  `gross_pay = ${revived.value} (${revived.evidence_kind}), codes: ${codes(after).join(", ") || "none"}`);
record("Sequence 1e — and the correction actually being made survives the undo of the other",
  kept.value === 2 && kept.evidence_kind === "corrected_by_renter",
  `household_size = ${kept.value} (${kept.evidence_kind})`);

/* ── sequence 2: delete, then carry on using the page ─────────────────────────── */
await next();   // 3
await next();   // 4
await next();   // 5
await next();   // 6

record("Sequence 2a — the renter can delete from inside the six steps, not only from the judges' page",
  await page.locator("#packet-delete-session").isVisible(),
  "delete control present on step 6");

const before = await activeSessions();
/* On a build where the journey has no delete control, fall back to the judge-facing one
 * so the checks after this one still run and report. 2a has already said what is
 * missing; stopping here would hide everything downstream of it. */
if (await page.locator("#packet-delete-session").count()) {
  await page.locator("#packet-delete-session").click();
} else {
  await page.locator("#go-how").click();
  await page.waitForTimeout(200);
  await page.getByRole("button", { name: "Delete session data now" }).click();
}
await page.locator("#packet-delete-note .callout, #session-output .callout")
  .first().waitFor({ timeout: 15000 });
const outcome = ((await page.locator("#packet-delete-note").textContent().catch(() => "")) || "") +
  ((await page.locator("#session-output").textContent().catch(() => "")) || "");
record("Sequence 2b — deletion is proved by a real follow-up request, not asserted",
  /HTTP 404/.test(outcome),
  (outcome.match(/GET [^\n]*HTTP \d+[^\n]*/) || ["no probe line"])[0].trim().slice(0, 110));

const emptied = await shownReport();
record("Sequence 2c — the page empties itself instead of still showing the household",
  emptied === null && (await page.locator("#packet-download").count()) === 0,
  `report held: ${emptied === null ? "none" : emptied.household_id}, download buttons: ${await page.locator("#packet-download").count()}`);

/* Read the whole screen, not one panel: what matters is that the person standing on
 * step 6 is told, wherever on it the sentence happens to be rendered. */
const saysSo = ((await page.locator("#screen-6").textContent().catch(() => "")) || "") +
  ((await page.locator("#session-output").textContent().catch(() => "")) || "");
record("Sequence 2d — the screen says what happened and that carrying on means starting again",
  /deleted this session/i.test(saysSo) && /start(ing)? again/i.test(saysSo),
  saysSo.replace(/\s+/g, " ").trim().slice(0, 100));

/* Walk back through the steps the way a judge would after deleting. This is the exact
 * move that used to resurrect everything: any screen making a request was enough. */
if (await page.locator("#nav-how button").count()) {
  await page.locator("#nav-how button").first().click();   // "go back to where you were"
  await page.waitForTimeout(400);
}
for (const _ of [0, 1]) {
  if (await page.locator("#step-back").count()) {
    await page.locator("#step-back").click();
    await page.waitForTimeout(250);
  }
}
await page.waitForTimeout(400);
const afterWalking = await shownReport();
const sessionsNow = await activeSessions();
record("Sequence 2e — going back does not quietly mint a new session and re-load the pack",
  afterWalking === null && sessionsNow <= before - 1,
  `sessions ${before} -> ${sessionsNow}, report held: ${afterWalking === null ? "none" : afterWalking.household_id}`);

const stillGone = await page.evaluate(async (apiBase) => {
  const probe = await fetch(`${apiBase}/api/households`);
  return probe.status;
}, base).catch(() => null);
record("Sequence 2f — the API refuses an unidentified request rather than opening a session",
  stillGone === 400, `GET /api/households with no session id -> ${stillGone}`);

/* Starting again is offered, and is honest about being a new session rather than a
 * restore. A build that offers no way forward at all fails here rather than throwing:
 * "there is nothing you can do next" is a result worth printing. */
const restart = page.getByRole("button", { name: /Start again with a new session/ }).first();
if (await restart.count()) {
  await restart.click();
  await page.waitForFunction(() => window.REALDOOR_LAST_REPORT !== null, { timeout: 20000 });
  const restarted = await shownReport();
  const restartedField = fieldValue(restarted, "HH-004-D01", "household_size");
  record("Sequence 2g — starting again loads the pack fresh; the deleted corrections are not restored",
    restarted !== null && restartedField.evidence_kind === "extracted",
    `household_size = ${restartedField.value} (${restartedField.evidence_kind})`);
} else {
  record("Sequence 2g — starting again loads the pack fresh; the deleted corrections are not restored",
    false, "no way to start again is offered after a deletion");
}

const passed = checks.filter((c) => c.ok).length;
console.log(`\n${passed}/${checks.length} journey-order checks passed`);
await browser.close();
process.exit(passed === checks.length ? 0 : 1);
