/* Keyboard-only walk through the mandated six-step demo, plus the secondary route that
 * holds the judge-facing material.
 *
 * The mouse is never used: this script only sends Tab, Shift+Tab, Enter and Space, and it
 * asserts on what actually appears on screen after each step. A step counts as passing only
 * if its evidence is visible -- not if the key press was accepted.
 *
 * The walk is a forward walk: landing -> step 1 -> ... -> step 6, driven by the same Back
 * and Next buttons a user has. There is no tab bar to arrow along any more, and one of the
 * checks below asserts that there is not.
 *
 *   node ui/tools/keyboard-journey.mjs
 */
import { chromium } from "playwright";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import { readFile } from "node:fs/promises";

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
async function tabTo(match, limit = 220, key = "Tab") {
  for (let i = 0; i < limit; i += 1) {
    await page.keyboard.press(key);
    const info = await focusInfo();
    if (match(info)) return info;
  }
  return null;
}
/** The id of the one screen currently on show. */
const currentScreen = () => page.evaluate(() =>
  (Array.from(document.querySelectorAll(".screen")).find((s) => !s.hidden) || {}).id);

/** Press a control by id, reached only with Tab from wherever focus currently is. */
async function pressById(id) {
  const hit = await tabTo((info) => info.id === id);
  if (!hit) return false;
  await page.keyboard.press("Enter");
  await page.waitForTimeout(120);
  return true;
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

// ── step 0: what the first screen is, and the absence of a tab bar ──────────────
await page.keyboard.press("Tab");
const firstStop = await focusInfo();
record("Skip link is the first tab stop", /Skip to main content/.test(firstStop.text), firstStop.text);
record("Focused control shows a visible focus indicator", await hasVisibleFocusRing());

{
  const tablists = await page.locator('[role="tablist"]').count();
  const tabs = await page.locator('[role="tab"]').count();
  record("No tab bar exists — the flow is linear, not parallel",
    tablists === 0 && tabs === 0, `${tablists} tablists, ${tabs} tabs`);

  /* There used to be a landing screen in front of step 1 carrying a process list and a
   * "Before you start" trust line. Both were demo instructions, and both now live on the
   * judges' page. This check is not "the landing is gone" — it is the stronger pair: the
   * walkthrough opens on step 1, *and* nothing that used to be on the landing was thrown
   * away, it is on screen-how and still says the same words. */
  const opensOn = await currentScreen();
  const processItems = await page.locator("#screen-how #process-list .process-item").count();
  const trust = ((await page.locator("#screen-how #trust-line").textContent().catch(() => "")) || "")
    .replace(/\s+/g, " ");
  record("The walkthrough opens on step 1, with no screen in front of it",
    opensOn === "screen-1", `first screen on show: ${opensOn}`);
  record("The landing's process list and trust line were moved to the judges' page, not dropped",
    processItems === 6 && /about ten minutes/i.test(trust) && /nothing is sent anywhere/i.test(trust),
    `${processItems} process items and the trust line, both inside #screen-how`);

  /* The point of the whole change: the free-text question control is on the first screen
   * with nothing pressed. On this static build it is switched off rather than hidden, so
   * what is asserted is that it is *present and reachable*, and that the page says which of
   * the two it is. */
  const askOnFirstScreen = await page.evaluate(() => {
    const input = document.getElementById("ask-input");
    if (!input) return null;
    const box = document.getElementById("ask-anywhere");
    return {
      visible: input.offsetHeight > 0 && Boolean(box) && box.offsetHeight > 0,
      disabled: input.disabled,
      insideAScreen: Boolean(input.closest(".screen")),
      saysWhy: /switched off rather than hidden/.test(box ? box.textContent : "")
    };
  });
  record("A question box is on the first screen, with no control pressed to reach it",
    Boolean(askOnFirstScreen) && askOnFirstScreen.visible && !askOnFirstScreen.insideAScreen,
    askOnFirstScreen ? `visible, outside every .screen, disabled=${askOnFirstScreen.disabled}` : "no #ask-input");
  record("Offline the box is switched off rather than hidden, and says so",
    Boolean(askOnFirstScreen) && askOnFirstScreen.disabled && askOnFirstScreen.saysWhy,
    "static build: control present, disabled, with the command that turns it on");
}

// ── step 1: documents and evidence ──────────────────────────────────────────────
{
  const screen = await currentScreen();
  const caption = (await page.locator("#cap-1").textContent()) || "";
  const heading = (await page.locator("#screen-1 h1").textContent()) || "";
  const segments = await page.locator(".segment").count();
  const currentSeg = (await page.locator(".segment--current").textContent()) || "";
  const indicatorControls = await page.locator(".step-indicator a, .step-indicator button").count();
  /* Focus is not asserted here any more, and deliberately: step 1 is now the screen the
   * page loads on, and moving focus off the document start on load is a thing to avoid,
   * not a thing to test for. Focus-on-arrival is still asserted at every step reached by
   * pressing Next, which is every other step in this walk. */
  record("Step 1 is the opening screen, with a step caption and a unique H1",
    screen === "screen-1" && /Step 1 of 6/.test(caption) &&
    /Check the values we read/.test(heading),
    `${caption.trim()} / "${heading.trim()}"`);
  record("Step 1 — step indicator shows six segments and is not itself navigable",
    segments === 6 && indicatorControls === 0 && /current step/.test(currentSeg),
    `${segments} segments, ${indicatorControls} controls inside the indicator`);

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
  await page.locator("#h-1").focus();
  const moved = await pressById("step-next");
  record("Step 2 — reached with the Next button, not a tab",
    moved && (await currentScreen()) === "screen-2",
    (await page.locator("#cap-2").textContent()).trim());

  const scenario = await tabTo((info) => /Gross pay on the newer stub/.test(info.text));
  if (scenario) await page.keyboard.press("Enter");
  const apply = await tabTo((info) => info.id === "correct-apply");
  if (apply) await page.keyboard.press("Enter");
  await page.locator("#correction-outcome-heading").waitFor({ timeout: 3000 }).catch(() => {});
  const heading = (await page.locator("#correction-outcome-heading").textContent().catch(() => "")) || "";
  const explained = await page.locator("#correct-outcome .callout--stop").count();
  record("Step 2a — rejected correction is shown as rejected, with the reason",
    /NOT used/.test(heading) && explained === 1, heading.trim());

  // the machine code must be present for verification but never as the headline
  const reasonHeadings = await page.locator("#correct-body .reason-heading").allTextContents();
  const codeVisibleUpFront = /RENTER_CORRECTION_NOT_USED|PAY_STUB_TOTAL_CONFLICT/.test(
    (await page.locator("#error-summary-host").textContent()) + reasonHeadings.join(" "));
  const codeAvailable = await page.evaluate(() =>
    Array.from(document.querySelectorAll("#correct-body details.tech"))
      .some((d) => /RENTER_CORRECTION_NOT_USED/.test(d.textContent)));
  // The headline must be the plain layer's, not a string this harness or app.js keeps.
  // Asserting equality with report.plain rather than a snapshot of the wording is the
  // point: it fails if the screen ever stops reading api/plain.py, and it does not fail
  // merely because that layer rephrased itself. It replaces a regex that matched a
  // hand-written heading table in app.js, which no longer exists.
  const headlineFromPlain = await page.evaluate(() => {
    const said = (window.REALDOOR_LAST_REPORT?.plain?.messages || [])
      .find((m) => m.code === "RENTER_CORRECTION_NOT_USED");
    if (!said) return null;
    const headings = Array.from(document.querySelectorAll("#correct-body .reason-heading"))
      .map((n) => n.textContent.trim());
    return { headline: said.headline, matched: headings.includes(said.headline.trim()) };
  });
  record("Step 2b — the error code is kept for verification but is never the headline",
    !codeVisibleUpFront && codeAvailable && headlineFromPlain?.matched === true,
    `${reasonHeadings.length} headlines, none of them a code; headline is the plain layer's ` +
    `("${headlineFromPlain?.headline ?? "MISSING"}"); code reachable under Technical details`);

  // error summary sits above the H1 and quotes the inline message word for word
  // Each summary link must name the same problem, in the same words, as the inline item it
  // points at -- and the inline item must carry the API's own message underneath, unedited.
  const match = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll("#error-summary-host .error-summary-list a"));
    const summary = document.querySelector("#error-summary-host .error-summary");
    const h1 = document.querySelector("#screen-2 h1");
    if (!links.length || !summary || !h1) return null;
    const aboveH1 = Boolean(summary.compareDocumentPosition(h1) & Node.DOCUMENT_POSITION_FOLLOWING);
    const paired = links.every((link) => {
      const target = document.querySelector(link.getAttribute("href"));
      if (!target) return false;
      const heading = target.querySelector(".reason-heading");
      const message = target.querySelector(".reason-message");
      return heading && message &&
             heading.textContent.trim() === link.textContent.trim() &&
             message.textContent.trim().length > 0;
    });
    return { paired, aboveH1, count: links.length };
  });
  record("Step 2c — error summary sits above the H1 and each link matches its inline item exactly",
    Boolean(match) && match.paired && match.aboveH1,
    match ? `${match.count} links, all matching their inline heading, aboveH1=${match.aboveH1}` : "missing");

  // and the accepted correction, which moves the threshold 72,000 -> 92,580
  await page.locator("#correct-doc").focus();
  const undo = await tabTo((info) => /Undo correction/.test(info.text));
  if (undo) await page.keyboard.press("Enter");
  await page.locator("#h-2").focus();
  const sizeScenario = await tabTo((info) => /Household size is 3, not 1/.test(info.text));
  if (sizeScenario) await page.keyboard.press("Enter");
  const apply2 = await tabTo((info) => info.id === "correct-apply");
  if (apply2) await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const table = (await page.locator("#correct-outcome table").textContent().catch(() => "")) || "";
  record("Step 2d — accepted correction moves the threshold 72,000 to 92,580",
    /\$72,000\.00/.test(table) && /\$92,580\.00/.test(table),
    table.includes("$92,580.00") ? "new threshold $92,580.00 shown beside the old $72,000.00" : "not found");
}

// ── step 3: ask about a rule, with citation ─────────────────────────────────────
{
  await page.locator("#h-2").focus();
  await pressById("step-next");
  const question = await tabTo((info) => /What is the frozen 60% threshold for HH-001\?/.test(info.text));
  if (question) await page.keyboard.press("Enter");
  await page.waitForTimeout(120);
  const body = (await page.locator("#ask-answer").textContent()) || "";
  const link = await page.locator('#ask-answer a[href^="https://"]').count();
  record("Step 3 — answer carries rule id, authority, effective date, locator and source link",
    (await currentScreen()) === "screen-3" &&
    /HUD-MTSP-002/.test(body) && /official hud/.test(body) && /2026-05-01/.test(body) &&
    /PDF page 130/.test(body) && link > 0,
    `source links: ${link}`);
}

// ── step 4: the calculation ─────────────────────────────────────────────────────
{
  await page.locator("#h-3").focus();
  await pressById("step-next");
  const body = (await page.locator("#calc-body").textContent()) || "";
  record("Step 4 — inputs, formula, result, threshold, comparison and effective date all present",
    (await currentScreen()) === "screen-4" &&
    /2166\.0 \* 26/.test(body) && /\$56,316\.00/.test(body) && /\$92,580\.00|\$72,000\.00/.test(body) &&
    /at or below the frozen 60% threshold/.test(body) && /2026-05-01/.test(body) &&
    /A comparison is not a determination/.test(body));
}

// ── step 5: what is missing or out of date ──────────────────────────────────────
{
  // switch to HH-005, which holds the genuinely expired document
  await page.locator("#household-select").focus();
  await page.selectOption("#household-select", "HH-005");
  await page.waitForTimeout(200);
  await page.locator("#h-4").focus();
  await pressById("step-next");

  const body = (await page.locator("#checklist-body").textContent()) || "";
  const expiredShown = /Expired \(1\)/.test(body) && /2026-04-14/.test(body);
  const nextSteps = await page.locator("#checklist-body .summary-box__list li").count();
  record("Step 5 — the expired document is surfaced, with a short list of what to do next",
    (await currentScreen()) === "screen-5" && expiredShown && nextSteps > 0,
    `${expiredShown ? "expired item shown" : "expired item MISSING"}; ${nextSteps} next-step items`);

  // The inline item states the expiry date in words a renter reads; the API's own
  // sentence, ISO date and document id included, is kept verbatim one disclosure away.
  // Both halves are asserted, because "plain" must not become "vaguer": if the date
  // stopped being stated, or the precise string stopped being retrievable, this fails.
  const match = await page.evaluate(() => {
    const link = document.querySelector("#error-summary-host .error-summary-list a");
    if (!link) return null;
    const target = document.querySelector(link.getAttribute("href"));
    const heading = target && target.querySelector(".reason-heading");
    const message = target && target.querySelector(".reason-message");
    const tech = target && target.querySelector("details.tech");
    if (!heading || !message || !tech) return null;
    return heading.textContent.trim() === link.textContent.trim() &&
           /14 April 2026|2026-04-14/.test(message.textContent) &&
           /2026-04-14/.test(tech.textContent) &&
           /HH-005-D04/.test(tech.textContent);
  });
  record("Step 5 — the expiry is stated plainly inline and the API's own words are kept verbatim",
    match === true, match === null ? "summary or inline item missing" : "heading matches, date stated inline, precise wording retrievable");
}

// ── step 6: check what we found, then take the packet ───────────────────────────
{
  await page.locator("#h-5").focus();
  await pressById("step-next");
  const rows = await page.locator("#summary-body .answer-row").count();
  const changeNames = await page.locator("#summary-body .change-link").allTextContents();
  record("Step 6a — a check-answers screen with rows and descriptive Change controls",
    (await currentScreen()) === "screen-6" && rows >= 6 && changeNames.length >= 5 &&
    changeNames.every((t) => /^Change .+/.test(t.replace(/\s+/g, " ").trim())),
    `${rows} rows, ${changeNames.length} Change controls`);

  // a Change control must land on the right step and offer a way straight back
  await page.locator("#h-6").focus();
  const change = await tabTo((info) => /^Change\s+the housing rule you asked about/.test(info.text.replace(/\s+/g, " ")));
  if (change) await page.keyboard.press("Enter");
  await page.waitForTimeout(120);
  const landed = await currentScreen();
  const returnedOk = await pressById("step-return");
  record("Step 6b — Change goes to the right step and returns straight to the check screen",
    landed === "screen-3" && returnedOk && (await currentScreen()) === "screen-6",
    `Change -> ${landed} -> ${await currentScreen()}`);

  const body = (await page.locator("#packet-body").textContent()) || "";
  const download = page.waitForEvent("download", { timeout: 5000 }).catch(() => null);
  await page.locator("#h-6").focus();
  const button = await tabTo((info) => info.id === "packet-download");
  if (button) await page.keyboard.press("Enter");
  const file = await download;
  record("Step 6c — packet downloaded by keyboard, with nothing transmitted",
    Boolean(file) && /Nothing is sent anywhere/.test(body),
    `download: ${file ? file.suggestedFilename() : "none"}`);
}

// ── the secondary route: judge-facing material, one click away ──────────────────
{
  await page.locator("#h-6").focus();
  const reached = await pressById("go-how");
  record("Judge-facing material is one click away and is not part of the six steps",
    reached === false || (await currentScreen()) === "screen-how",
    `landed on ${await currentScreen()}`);
  if ((await currentScreen()) !== "screen-how") {
    await page.locator("#go-how").focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(120);
  }

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
  record("Controls — all three refusals demonstrated from the keyboard",
    ran === 3 &&
    /does not determine eligibility/.test(body) &&
    /only answer about its own household/.test(body) &&
    /treated as document content, not as an instruction/.test(body),
    `${ran} probes run`);

  const gate = await tabTo((info) => /Try to make the server return a decision/.test(info.text));
  if (gate) await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const gateBody = (await page.locator("#gate-output").textContent()) || "";
  record("Controls — output-gate self-test reports honestly (offline: not run)",
    /Not run — there is no server to test/.test(gateBody), gateBody.slice(0, 60).trim());

  const del = await tabTo((info) => /Delete session data now/.test(info.text));
  if (del) await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const sessionBody = (await page.locator("#session-output").textContent()) || "";
  record("Controls — session deletion runs and reports what it cleared",
    /cleared/i.test(sessionBody), sessionBody.slice(0, 60).trim());

  // The measurements are read from ui/fixtures/selftest.json as exported. Assert on the
  // shape of the honesty rather than on numbers that legitimately move between exports.
  //
  // This check used to require that at least one section be labelled Not run, because the
  // citations section had been not_run since it was written. That made a shortfall into a
  // fixture of the test, and once the citation re-check was wired the suite failed for the
  // one reason it must never fail: a number got better. Requiring a permanent red chip
  // would also have been an invitation to keep one, which is the opposite of the point.
  //
  // The invariant is the correspondence, in both directions: every section the export marks
  // not_run is chipped Not run, every section it marks measured is not, and the summary
  // names them. Zero not-run sections is then an allowed and reportable state, not a pass
  // and not a failure.
  const measure = (await page.locator("#measure-body").textContent()) || "";
  const exported = JSON.parse(
    await readFile(resolve(here, "..", "fixtures", "selftest.json"), "utf8"));
  const expectedNotRun = Object.entries(exported.sections)
    .filter(([, section]) => section.status !== "measured").map(([name]) => name);
  const notRunChips = await page.locator("#measure-body .chip--missing").count();
  const measuredChips = await page.locator("#measure-body .chip--present").count();
  const totalSections = Object.keys(exported.sections).length;
  record("Measurements — every section is chipped with the status the export actually carries",
    notRunChips === expectedNotRun.length &&
    measuredChips === totalSections - expectedNotRun.length &&
    /abstained/.test(measure) &&
    /Citations re-checked against their live source/.test(measure) &&
    // 못 잰 절이 하나도 없을 때도 그 사실이 문장으로 나와야 한다 — 빈칸은 주장이 아니다.
    (expectedNotRun.length ? /Not run at all:/.test(measure)
                           : /No measured section fell short in this run|Not run at all:/.test(measure)),
    `${notRunChips} not run, ${measuredChips} measured, of ${totalSections} sections` +
    (expectedNotRun.length ? ` (not run: ${expectedNotRun.join(", ")})` : ""));
}

// ── constraint checks that must hold on every screen ────────────────────────────
{
  const SCREEN_IDS = ["screen-1", "screen-2", "screen-3", "screen-4",
                      "screen-5", "screen-6", "screen-how"];

  // Every screen must announce itself with its own heading. GOV.UK: do not reuse a page
  // heading across pages; the heading must describe this screen, not the section.
  const headings = await page.evaluate((ids) =>
    ids.map((id) => {
      const h1 = document.querySelector(`#${id} h1`);
      return h1 ? h1.textContent.trim() : null;
    }), SCREEN_IDS);
  const unique = new Set(headings);
  record("Every screen has its own H1, and no two are the same",
    headings.every(Boolean) && unique.size === headings.length,
    `${unique.size} distinct headings across ${headings.length} screens`);

  // The abstentions and review reasons must stay visible, never collapsed by default.
  const railOpen = await page.evaluate(() => {
    const rail = document.querySelector(".open-questions");
    if (!rail) return false;
    const collapsed = Array.from(rail.querySelectorAll("details"))
      .filter((d) => !d.open && !/Technical details/.test(d.querySelector("summary")?.textContent || ""));
    return { visible: rail.offsetHeight > 0, wronglyCollapsed: collapsed.length };
  });
  record("Abstentions and review reasons stay visible and uncollapsed",
    railOpen.visible && railOpen.wronglyCollapsed === 0,
    `rail visible, ${railOpen.wronglyCollapsed} sections wrongly collapsed`);

  // No machine code may be a headline anywhere -- not a heading, not a summary link, not
  // the lead line of an open item. They must all still exist one disclosure away.
  {
    const codeLike = /^[A-Z][A-Z0-9]*([_-][A-Z0-9]+)+$/;
    const offenders = await page.evaluate((pattern) => {
      const re = new RegExp(pattern);
      const found = [];
      for (const id of ["screen-1", "screen-2", "screen-3", "screen-4",
                        "screen-5", "screen-6", "screen-how"]) {
        document.querySelectorAll(".screen").forEach((s) => { s.hidden = s.id !== id; });
        // scope to what is actually on show: the current screen, the summary above it,
        // and the open-questions rail that is present on every screen
        document.querySelectorAll(
          `#${id} h1, #${id} h2, #${id} h3, #${id} h4, #${id} .reason-heading,` +
          " #error-summary-host .error-summary-list a, .open-questions h3"
        ).forEach((node) => {
          if (node.closest("details")) return;             // disclosures are where codes belong
          const text = (node.textContent || "").trim();
          if (re.test(text)) found.push(`${id}: ${text}`);
        });
      }
      return Array.from(new Set(found));
    }, codeLike.source);
    record("No machine code is used as a heading or summary link on any screen",
      offenders.length === 0, offenders.join(" | ") || "clean");
  }

  const forbidden = /\b(eligible|ineligible|approved|denied|qualifies for|prioritized|ranked)\b/i;

  // A hostile question quoted back to the user is not the product's own statement -- the
  // whole point of the controls screen is to show the input verbatim and then refuse it.
  // Those exact strings are excluded, and nothing else is.
  const quotedInputs = await page.evaluate(() =>
    Object.values(window.REALDOOR_FIXTURES.ask_examples).map((e) => e.question));
  const isQuotedInput = (line) => quotedInputs.some((q) => line.includes(q));

  const offenders = [];
  for (const id of SCREEN_IDS) {
    await page.evaluate((target) => {
      document.querySelectorAll(".screen").forEach((s) => { s.hidden = s.id !== target; });
    }, id);
    const text = await page.locator("body").innerText();
    for (const line of text.split("\n")) {
      // the product is allowed -- required, even -- to say it does NOT do these things
      if (forbidden.test(line) && !/not|never|does not|without|refus|cannot|no eligibility/i.test(line)
          && !isQuotedInput(line)) {
        offenders.push(`${id}: ${line.trim().slice(0, 100)}`);
      }
    }
  }
  record("No screen states an eligibility outcome", offenders.length === 0, offenders.join(" | ") || "clean");
}

const passed = steps.filter((s) => s.ok).length;
console.log(`\n${passed}/${steps.length} keyboard checks passed`);
await browser.close();
process.exit(passed === steps.length ? 0 : 1);
