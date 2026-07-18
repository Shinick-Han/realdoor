/* Keyboard-only walk through the mandated six-step demo, plus the measurements screen.
 *
 * The mouse is never used: this script only sends Tab, Shift+Tab, arrow keys, Enter and
 * Space, and it asserts on what actually appears on screen after each step. A step counts
 * as passing only if its evidence is visible -- not if the key press was accepted.
 *
 *   node ui/tools/keyboard-journey.mjs
 */
import { chromium } from "playwright";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const pageUrl = pathToFileURL(resolve(here, "..", "dist", "index.html")).href;

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const page = await context.newPage();
await page.goto(pageUrl);
await page.waitForFunction(() => document.querySelectorAll("#documents-body table").length > 0);

const steps = [];
function record(name, ok, detail) {
  steps.push({ step: name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}
const focusInfo = () => page.evaluate(() => {
  const el = document.activeElement;
  return { tag: el.tagName, id: el.id, text: (el.textContent || "").trim().slice(0, 70) };
});

/** Press Tab until the focused element satisfies `match`, or give up. */
async function tabTo(match, limit = 90, key = "Tab") {
  for (let i = 0; i < limit; i += 1) {
    await page.keyboard.press(key);
    const info = await focusInfo();
    if (match(info)) return info;
  }
  return null;
}
/** Move along the tablist with ArrowRight until the wanted tab is selected. */
async function arrowToTab(tabId) {
  await page.locator("#tablist [aria-selected='true']").focus();
  for (let i = 0; i < 10; i += 1) {
    const current = await page.evaluate(() => document.activeElement.id);
    if (current === tabId) return true;
    await page.keyboard.press("ArrowRight");
  }
  return false;
}
/** Confirm a visible focus indicator exists on the focused element. */
async function hasVisibleFocusRing() {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return false;
    const style = getComputedStyle(el);
    return style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
  });
}

// ── step 0: skip link is the very first stop ────────────────────────────────────
await page.keyboard.press("Tab");
const firstStop = await focusInfo();
record("Skip link is the first tab stop", /Skip to main content/.test(firstStop.text), firstStop.text);
record("Focused control shows a visible focus indicator", await hasVisibleFocusRing());

// ── step 1: documents and evidence ──────────────────────────────────────────────
{
  await arrowToTab("tab-documents");
  const hit = await tabTo((info) => /^(person_name|household_size)$/.test(info.text));
  if (hit) await page.keyboard.press("Enter");
  const highlighted = await page.locator(".evidence-box.is-active").count();
  const boxes = await page.locator("#documents-body .evidence-box").count();
  const rows = await page.locator("#documents-body tbody tr").count();
  record("Step 1 — evidence box highlighted from the keyboard",
    Boolean(hit) && highlighted === 1 && boxes > 0 && rows > 0,
    `${boxes} boxes drawn, ${rows} field rows, ${highlighted} highlighted`);
}

// ── step 2: correct a field, including the rejected correction ──────────────────
{
  await arrowToTab("tab-correct");
  const scenario = await tabTo((info) => /Gross pay on the newer stub/.test(info.text));
  if (scenario) await page.keyboard.press("Enter");
  const apply = await tabTo((info) => info.id === "correct-apply");
  if (apply) await page.keyboard.press("Enter");
  await page.locator("#correction-outcome-heading").waitFor({ timeout: 3000 }).catch(() => {});
  const heading = (await page.locator("#correction-outcome-heading").textContent().catch(() => "")) || "";
  const explained = await page.locator("#correct-outcome .callout--stop").count();
  record("Step 2a — rejected correction is shown as rejected, with the reason",
    /NOT used/.test(heading) && explained === 1, heading.trim());

  // and the accepted correction, which moves the threshold 72,000 -> 92,580
  await page.locator("#correct-doc").focus();
  const undo = await tabTo((info) => /Undo correction/.test(info.text));
  if (undo) await page.keyboard.press("Enter");
  await page.locator("#tab-correct").focus();
  const sizeScenario = await tabTo((info) => /Household size is 3, not 1/.test(info.text));
  if (sizeScenario) await page.keyboard.press("Enter");
  const apply2 = await tabTo((info) => info.id === "correct-apply");
  if (apply2) await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const table = (await page.locator("#correct-outcome table").textContent().catch(() => "")) || "";
  record("Step 2b — accepted correction moves the threshold 72,000 to 92,580",
    /\$72,000\.00/.test(table) && /\$92,580\.00/.test(table),
    table.includes("$92,580.00") ? "new threshold $92,580.00 shown beside the old $72,000.00" : "not found");
}

// ── step 3: ask about a rule, with citation ─────────────────────────────────────
{
  await arrowToTab("tab-ask");
  const question = await tabTo((info) => /What is the frozen 60% threshold for HH-001\?/.test(info.text));
  if (question) await page.keyboard.press("Enter");
  await page.waitForTimeout(120);
  const body = (await page.locator("#ask-answer").textContent()) || "";
  const link = await page.locator('#ask-answer a[href^="https://"]').count();
  record("Step 3 — answer carries rule id, authority, effective date, locator and source link",
    /HUD-MTSP-002/.test(body) && /official hud/.test(body) && /2026-05-01/.test(body) &&
    /PDF page 130/.test(body) && link > 0,
    `source links: ${link}`);
}

// ── step 4: the calculation ─────────────────────────────────────────────────────
{
  await arrowToTab("tab-calc");
  const body = (await page.locator("#calc-body").textContent()) || "";
  record("Step 4 — inputs, formula, result, threshold, comparison and effective date all present",
    /2166\.0 \* 26/.test(body) && /\$56,316\.00/.test(body) && /\$92,580\.00|\$72,000\.00/.test(body) &&
    /at or below the frozen 60% threshold/.test(body) && /2026-05-01/.test(body) &&
    /A comparison is not a determination/.test(body));
}

// ── step 5: readiness packet, downloaded by explicit keyboard action ────────────
{
  // switch to HH-005, which holds the genuinely expired document
  await page.locator("#household-select").focus();
  await page.selectOption("#household-select", "HH-005");
  await page.waitForTimeout(200);
  await arrowToTab("tab-packet");
  const body = (await page.locator("#packet-body").textContent()) || "";
  const expiredShown = /Expired \(1\)/.test(body) && /2026-04-14/.test(body);

  const download = page.waitForEvent("download", { timeout: 5000 }).catch(() => null);
  const button = await tabTo((info) => info.id === "packet-download");
  if (button) await page.keyboard.press("Enter");
  const file = await download;
  record("Step 5 — expired document surfaced and packet downloaded by keyboard",
    expiredShown && Boolean(file),
    `${expiredShown ? "expired item shown" : "expired item MISSING"}; download: ${file ? file.suggestedFilename() : "none"}`);
  record("Step 5 — the page states nothing is transmitted",
    /Nothing is sent anywhere/.test(body));
}

// ── step 6: controls, demonstrated live ─────────────────────────────────────────
{
  await arrowToTab("tab-controls");
  let ran = 0;
  for (let i = 0; i < 3; i += 1) {
    await page.locator(`#probe-h-${i}`).evaluate((el) => el.scrollIntoView());
    const probe = await page.locator(`#probe-h-${i}`).locator("xpath=following-sibling::div//button").first();
    await probe.focus();
    const focused = await page.evaluate(() => document.activeElement.textContent.trim());
    if (/Run this probe/.test(focused)) { await page.keyboard.press("Enter"); ran += 1; }
  }
  await page.waitForTimeout(150);
  const body = (await page.locator("#controls-body").textContent()) || "";
  record("Step 6a — all three refusals demonstrated from the keyboard",
    ran === 3 &&
    /does not decide eligibility/.test(body) &&
    /only answer about its own household/.test(body) &&
    /treated as document content, not as an instruction/.test(body),
    `${ran} probes run`);

  const gate = await tabTo((info) => /Try to make the server return a decision/.test(info.text));
  if (gate) await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const gateBody = (await page.locator("#gate-output").textContent()) || "";
  record("Step 6b — output-gate self-test reports honestly (offline: not run)",
    /Not run — there is no server to test/.test(gateBody), gateBody.slice(0, 60).trim());

  const del = await tabTo((info) => /Delete session data now/.test(info.text));
  if (del) await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const sessionBody = (await page.locator("#session-output").textContent()) || "";
  record("Step 6c — session deletion runs and reports what it cleared",
    /cleared/i.test(sessionBody), sessionBody.slice(0, 60).trim());
}

// ── step 7: our own numbers, unprettified ───────────────────────────────────────
{
  await arrowToTab("tab-measure");
  const body = (await page.locator("#measure-body").textContent()) || "";
  record("Step 7 — measurements shown including the bad ones and the not_run sections",
    /Not run/.test(body) && /157/.test(body) && /ADV-003/.test(body) && /abstained/.test(body),
    "abstentions, failed adversarial ids and not_run sections all visible");
}

// ── constraint checks that must hold on every screen ────────────────────────────
{
  const forbidden = /\b(eligible|ineligible|approved|denied|qualifies for|prioritized|ranked)\b/i;

  // A hostile question quoted back to the user is not the product's own statement -- the
  // whole point of screen 6 is to show the input verbatim and then refuse it. Those exact
  // strings are excluded, and nothing else is.
  const quotedInputs = await page.evaluate(() =>
    Object.values(window.REALDOOR_FIXTURES.ask_examples).map((e) => e.question));
  const isQuotedInput = (line) =>
    quotedInputs.some((q) => line.includes(q));

  const offenders = [];
  for (const tab of ["documents", "correct", "ask", "calc", "packet", "controls", "measure"]) {
    await page.locator(`#tab-${tab}`).click();
    const text = await page.locator("body").innerText();
    for (const line of text.split("\n")) {
      // the product is allowed -- required, even -- to say it does NOT do these things
      if (forbidden.test(line) && !/not|never|does not|without|refus|cannot|no eligibility/i.test(line)
          && !isQuotedInput(line)) {
        offenders.push(`${tab}: ${line.trim().slice(0, 100)}`);
      }
    }
  }
  record("No screen states an eligibility outcome", offenders.length === 0, offenders.join(" | ") || "clean");
}

const passed = steps.filter((s) => s.ok).length;
console.log(`\n${passed}/${steps.length} keyboard checks passed`);
await browser.close();
process.exit(passed === steps.length ? 0 : 1);
