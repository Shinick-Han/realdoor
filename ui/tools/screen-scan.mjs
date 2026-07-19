/* screen-scan.mjs — what a renter can actually see, measured on the rendered DOM.
 *
 * WHY THIS EXISTS
 * ===============
 * api/plain.py measures itself and reports, among other things, that 100% of
 * renter-facing strings are free of raw machine identifiers. That number was true and
 * beside the point: it measured the message layer, and the message layer was not wired
 * to the screen. The scorecard was describing strings nobody was being shown.
 *
 * So this measures the other end. It walks the six renter steps in the browser, reads the
 * text that is actually painted, and counts machine identifiers in it. The two numbers
 * answer different questions and both belong on the scorecard:
 *
 *     plain_language.free_of_raw_identifiers   — is the wording clean?
 *     rendered_screens.visible_identifiers     — is the wording on screen?
 *
 * WHAT COUNTS AS VISIBLE
 * ======================
 * Text inside a collapsed <details> is not counted, because it is not visible: that is
 * the whole design — machine codes are kept, one disclosure away, for anyone checking our
 * work. A <summary> is counted, because a collapsed disclosure still shows its summary.
 * Anything hidden by `hidden`, `display:none`, `visibility:hidden` or `.visually-hidden`
 * is excluded too, except that visually-hidden text IS counted when it would be read
 * aloud — a screen reader user meets it, so it is on screen for them.
 *
 * Counting is deliberately unforgiving. If this number is not zero, say so and show which
 * strings, on which screen. A measurement that can only report success measures nothing.
 *
 * Output: ui/screen-scan.json, read by api/selftest.py. If this has never been run, the
 * scorecard says not_run rather than guessing a number.
 *
 *   node ui/tools/screen-scan.mjs
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const uiDir = resolve(here, "..");
const distDir = resolve(uiDir, "dist");

// file://, deliberately: this is how the submitted bundle opens, with the fixtures in
// ui/dist/fixtures.js and no server anywhere. Measuring the live API instead would prove
// nothing about what a judge who double-clicks index.html sees.
const url = pathToFileURL(resolve(distDir, "index.html")).href;

// The households worth walking: one that is ready, one carrying three abstentions and
// three review reasons, and one whose only problem is an expired document.
const HOUSEHOLDS = ["HH-001", "HH-004", "HH-005"];

/* The identifier shapes the reasoning layer speaks in. A renter has no use for any of
 * them, and each was visible on the checklist screen before the plain layer was wired. */
const PATTERNS = [
  { name: "document_id", source: "HH-\\d{3}-D\\d{2}" },
  { name: "checklist_item_id", source: "CHK-[A-Z][A-Z-]+" },
  { name: "rule_id", source: "CH-[A-Z]+-\\d+" }
];

/* Household ids are counted and reported separately, never folded into the total. They
 * are not leaked internals on this screen: the picker in the header is labelled
 * "Household" and naming the file you are looking at is the one place the id is the
 * honest word for the thing. Reported so the choice stays visible rather than assumed. */
const HOUSEHOLD_ID = "HH-\\d{3}(?!-D)";

const STEPS = [
  { id: "step1-documents", screen: "screen-1" },
  // Step 2 is scanned with a correction applied, because that is the state that renders
  // reason cards; without it the screen has nothing to say. Best effort: the scenario
  // buttons differ per household, so a household that offers none is scanned as it stands
  // rather than skipped.
  { id: "step2-correct", screen: "screen-2", setUp: async (page) => {
      await page.locator("#correct-body .button-row").first().locator("button").nth(1)
        .click({ timeout: 2000 });
      await page.locator("#correct-apply").click({ timeout: 2000 });
      await page.locator("#correction-outcome-heading").waitFor({ timeout: 2000 });
    } },
  { id: "step3-ask", screen: "screen-3" },
  { id: "step4-calculation", screen: "screen-4" },
  { id: "step5-checklist", screen: "screen-5" },
  { id: "step6-check-and-packet", screen: "screen-6" }
];

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error)));

const households = [];

for (const householdId of HOUSEHOLDS) {
  // A fresh load per household, then the app's own controls: the walkthrough opens on step
  // 1, so there is nothing to press to enter it. The picker chooses the file and #step-next
  // advances. Toggling `.screen[hidden]`
  // directly would be quicker and wrong — the router *moves* the household picker into
  // the current screen, so a hand-hidden screen takes the picker down with it, and more
  // to the point a walk that skips the navigation is not a walk through the flow.
  await page.goto(url);

  // Step 1 opens with nothing loaded now; one click opens the prepared example.
  await page.locator("#example-open button").waitFor({ timeout: 30000 });
  await page.locator("#example-open button").click();
  await page.waitForFunction(() => document.querySelectorAll("#documents-body table").length > 0);
  await page.locator("#household-select").waitFor({ state: "visible" });
  await page.selectOption("#household-select", householdId);
  await page.waitForTimeout(250);

  const screens = [];
  for (const step of STEPS) {
    if (step.screen !== "screen-1") {
      await page.locator("#step-next").click();
      await page.waitForTimeout(150);
    }
    if (step.setUp) await step.setUp(page).catch(() => {});
    await page.waitForTimeout(120);

    const onScreen = await page.evaluate((id) => {
      const el = document.getElementById(id);
      return Boolean(el && !el.hidden);
    }, step.screen);
    if (!onScreen) throw new Error(`${householdId}: could not reach ${step.screen}`);

    const found = await page.evaluate(({ screen, patterns, householdPattern }) => {
      const compiled = patterns.map((p) => ({ name: p.name, re: new RegExp(p.source, "g") }));
      const householdRe = new RegExp(householdPattern, "g");

      /* Is this text node painted? Collapsed disclosures are the interesting case: their
       * contents are in the DOM and in textContent, but nobody can read them without
       * opening the disclosure, which is exactly the affordance we built. */
      function visible(node) {
        for (let el = node.parentElement; el; el = el.parentElement) {
          if (el.hidden) return false;
          const style = getComputedStyle(el);
          if (style.display === "none" || style.visibility === "hidden") return false;
          if (el.tagName === "DETAILS" && !el.open) {
            // the summary of a collapsed disclosure is still on show; its body is not
            let inSummary = false;
            for (let n = node.parentElement; n && n !== el; n = n.parentElement) {
              if (n.tagName === "SUMMARY") inSummary = true;
            }
            if (!inSummary) return false;
          }
        }
        return true;
      }

      const roots = [
        document.getElementById(screen),
        document.querySelector(".open-questions"),
        document.getElementById("error-summary-host"),
        document.querySelector(".site-header")
      ].filter(Boolean);

      const hits = [];
      let householdIds = 0;
      const seenNodes = new Set();

      for (const root of roots) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (seenNodes.has(node)) continue;
          seenNodes.add(node);
          const text = (node.nodeValue || "").trim();
          if (!text) continue;
          if (!visible(node)) continue;
          for (const { name, re } of compiled) {
            re.lastIndex = 0;
            let match;
            while ((match = re.exec(text)) !== null) {
              hits.push({
                pattern: name,
                identifier: match[0],
                // enough surrounding text to find it by eye, never the whole node
                context: text.slice(Math.max(0, match.index - 45), match.index + 60).trim()
              });
            }
          }
          householdRe.lastIndex = 0;
          while (householdRe.exec(text) !== null) householdIds++;
        }
      }
      return { hits, householdIds };
    }, { screen: step.screen, patterns: PATTERNS, householdPattern: HOUSEHOLD_ID });

    screens.push({
      step: step.id,
      visible_identifiers: found.hits.length,
      household_ids_named: found.householdIds,
      offenders: found.hits
    });
    const flag = found.hits.length ? "  <-- " + found.hits.map((x) => x.identifier).join(", ") : "";
    console.log(
      `${householdId}  ${step.id.padEnd(24)} identifiers=${String(found.hits.length).padStart(2)}` +
      `  household_ids=${found.householdIds}${flag}`
    );
  }

  const gaps = await page.evaluate(() => (window.REALDOOR_PLAIN_GAPS || []).slice());
  households.push({
    household_id: householdId,
    visible_identifiers: screens.reduce((sum, s) => sum + s.visible_identifiers, 0),
    plain_wording_gaps: gaps,
    screens
  });
}

// Gaps accumulate across the whole session, so the last read is the full set.
const gaps = await page.evaluate(() => (window.REALDOOR_PLAIN_GAPS || []).slice());
const total = households.reduce((sum, hh) => sum + hh.visible_identifiers, 0);

// Where the remaining identifiers are, so the number is actionable rather than a mood.
const byStep = {};
for (const hh of households) {
  for (const s of hh.screens) {
    byStep[s.step] = (byStep[s.step] || 0) + s.visible_identifiers;
  }
}

const report = {
  tool: "screen-scan",
  by_step: byStep,
  page: "ui/dist/index.html",
  origin: "file:// (offline, bundled fixtures — the state the submitted build opens in)",
  generated_at: new Date().toISOString(),
  households_walked: HOUSEHOLDS,
  steps_per_household: STEPS.length,
  patterns: PATTERNS.map((p) => p.source),
  total_visible_identifiers: total,
  plain_wording_gaps: gaps,
  page_errors: pageErrors,
  method_note:
    "Counts machine identifiers in text that is painted on the six renter steps, plus the " +
    "always-visible open-questions rail, the error summary and the header. Text inside a " +
    "collapsed <details> is not counted: it is one disclosure away by design, and every " +
    "code and original message is still there. Household ids are counted separately and " +
    "excluded from the total, because the header picker names the file being read.",
  results: households
};
writeFileSync(resolve(uiDir, "screen-scan.json"), JSON.stringify(report, null, 1) + "\n");

console.log(`\nvisible machine identifiers: ${total} across ${HOUSEHOLDS.length} households x ${STEPS.length} steps`);
for (const [step, count] of Object.entries(byStep)) console.log(`    ${step.padEnd(24)} ${count}`);
console.log(`plain wording gaps: ${gaps.length}${gaps.length ? "  " + gaps.join(", ") : ""}`);
if (pageErrors.length) console.log(`page errors: ${pageErrors.length}\n  ${pageErrors.join("\n  ")}`);
console.log("written: ui/screen-scan.json");

await browser.close();

/* The exit code reports whether the measurement is trustworthy, not whether the number is
 * flattering. Two things make it untrustworthy and both fail here: a page error means we
 * measured a broken render, and a plain-wording gap means the screen fell back to older
 * wording, which is a defect in the wiring by definition. The identifier count itself is
 * published rather than gated: no threshold has been agreed for it, and inventing one
 * here so the script goes green is precisely the move this file exists to catch. */
process.exit(gaps.length === 0 && pageErrors.length === 0 ? 0 : 1);
