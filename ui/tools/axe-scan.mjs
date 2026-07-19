/* Accessibility measurement for the RealDoor UI.
 *
 * Drives ui/dist/index.html in headless Chromium over file:// -- the same way a judge
 * with no server would open it -- walks the landing screen, all six ordered steps and the
 * secondary "how this works" route, puts each one into the state a user actually reaches
 * (correction applied, probe run, packet section rendered), and runs axe-core against each.
 *
 * The walk is a real forward walk through the flow, using the same Back/Next controls a
 * user has, rather than jumping between panels: the flow is the thing being measured.
 *
 * Output: ui/axe-report.json. Violations are written whether or not they are zero.
 *
 *   node ui/tools/axe-scan.mjs
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, extname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const uiDir = resolve(here, "..");
const distDir = resolve(uiDir, "dist");
const axeSource = readFileSync(resolve(here, "node_modules", "axe-core", "axe.min.js"), "utf8");

/* Two origins are scanned, and the difference matters:
 *   file://  is how a judge opens the build with no server. Chromium refuses to let
 *            axe-core read the stylesheet across the opaque origin, so colour-contrast
 *            comes back "incomplete" -- unknown, not passing.
 *   http://  is how FastAPI serves ui/dist. Here axe can read the CSS, so the contrast
 *            verdict is real. Both are recorded so the file:// incompletes cannot be
 *            mistaken for hidden failures.
 */
const staticServer = createServer((request, response) => {
  const name = decodeURIComponent(request.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
  const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json" };
  try {
    const body = readFileSync(resolve(distDir, name));
    response.writeHead(200, { "Content-Type": types[extname(name)] || "application/octet-stream" });
    response.end(body);
  } catch {
    response.writeHead(404).end("not found");
  }
});
await new Promise((done) => staticServer.listen(0, "127.0.0.1", done));
const httpBase = `http://127.0.0.1:${staticServer.address().port}/index.html`;

/* The Korean origins exist because the language layer changes two things axe can judge:
 * <html lang>, which SC 3.1.1 requires to follow the language actually on screen, and the
 * rendered text itself, which changes every contrast and name-from-content calculation.
 * Scanning only the English build would leave the Korean build unmeasured while it was
 * still switchable in the UI. English remains the default and the canonical text; ?lang=ko
 * is the explicit opt-in, which is exactly how a user reaches it. */
const ORIGINS = [
  { id: "file", url: pathToFileURL(resolve(distDir, "index.html")).href },
  { id: "http", url: httpBase },
  { id: "file-ko", url: pathToFileURL(resolve(distDir, "index.html")).href + "?lang=ko" },
  { id: "http-ko", url: httpBase + "?lang=ko" }
];

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Each screen in flow order: how the user arrives, plus any interaction that must
 *  happen before scanning. `enter` uses only controls that exist on the previous screen.
 *
 *  Controls are addressed structurally (id, landmark, position) rather than by their
 *  visible English text wherever the language layer can translate that text. A selector
 *  that only matches in one language would silently skip the setup on the other origin
 *  and scan a screen in the wrong state -- which reads as a pass. The one exception is the
 *  recorded question below: those strings come from the challenge pack and are deliberately
 *  never translated, so matching them by name stays correct in both languages. */
const SCREENS = [
  // Step 1 is the screen the page opens on. There is no landing screen in front of it any
  // more: the walkthrough instructions it carried are on the "How this works" page, scanned
  // at the end of this list.
  { id: "step1-documents", enter: async () => {},
    setUp: async (page) => {
      await page.locator("#documents-body .field-row-btn").first().click();
    } },

  { id: "step2-correct", enter: async (page) => page.locator("#step-next").click(),
    setUp: async (page) => {
      // load the rejected-correction scenario: the case that must be prominent, and the
      // one that puts an error summary above the H1 with an inline item to match it
      await page.locator("#correct-body .button-row").first().locator("button").nth(1).click();
      await page.locator("#correct-apply").click();
      await page.locator("#correction-outcome-heading").waitFor();
    } },

  { id: "step3-ask", enter: async (page) => page.locator("#step-next").click(),
    setUp: async (page) => {
      await page.getByRole("button", { name: "What annualized income should the scorer use for HH-001?" }).click();
    } },

  { id: "step4-calculation", enter: async (page) => page.locator("#step-next").click() },

  { id: "step5-checklist", enter: async (page) => page.locator("#step-next").click() },

  { id: "step6-check-and-packet", enter: async (page) => page.locator("#step-next").click() },

  // the secondary route, reached in one click from wherever the user happens to be
  { id: "how-this-works", enter: async (page) => page.locator("#go-how").click(),
    setUp: async (page) => {
      for (const index of [0, 1, 2]) {
        await page.locator("#controls-body .card").nth(index).locator("button").first().click();
      }
      await page.locator("section[aria-labelledby='gate-h'] button").click();
      await page.locator("#gate-output .callout").waitFor();
    } }
];

const browser = await chromium.launch();
const consoleErrors = [];
const runs = [];
let axeVersion = null;

for (const origin of ORIGINS) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", (error) => consoleErrors.push(`[${origin.id}] ${error}`));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(`[${origin.id}] ${message.text()}`);
  });

  await page.goto(origin.url);
  await page.waitForFunction(() => document.querySelectorAll("#documents-body table").length > 0);

  const results = [];
  for (const screen of SCREENS) {
    await screen.enter(page);
    if (screen.setUp) await screen.setUp(page);
    await page.waitForTimeout(120);

    await page.evaluate(axeSource);
    const run = await page.evaluate(async (tags) => {
      const outcome = await window.axe.run(document, {
        runOnly: { type: "tag", values: tags },
        resultTypes: ["violations", "incomplete"]
      });
      return {
        violations: outcome.violations.map((v) => ({
          id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
          nodes: v.nodes.map((n) => ({ target: n.target, failureSummary: n.failureSummary }))
        })),
        incomplete: outcome.incomplete.map((v) => ({
          id: v.id, impact: v.impact, help: v.help,
          nodes: v.nodes.map((n) => ({
            target: n.target,
            reason: (n.any || []).map((check) => check.message).join(" / ")
          }))
        })),
        rules_passed: outcome.passes ? outcome.passes.length : null
      };
    }, WCAG_TAGS);

    results.push({ screen: screen.id, ...run });
    console.log(
      `${origin.id}  ${screen.id.padEnd(14)} violations=${String(run.violations.length).padStart(2)} ` +
      `incomplete=${String(run.incomplete.length).padStart(2)}`
    );
    for (const violation of run.violations) {
      console.log(`      - [${violation.impact}] ${violation.id}: ${violation.help}`);
      for (const node of violation.nodes) console.log(`          ${node.target}`);
    }
  }

  axeVersion = await page.evaluate(() => window.axe.version);
  runs.push({
    origin: origin.id,
    url: (origin.id.startsWith("file")
      ? "file:// (offline, bundled fixtures)"
      : "http:// (as FastAPI serves ui/dist)") +
      (origin.id.endsWith("-ko") ? ", ?lang=ko (Korean reading layer on, html lang=ko)" : ""),
    total_violations: results.reduce((sum, r) => sum + r.violations.length, 0),
    total_incomplete: results.reduce((sum, r) => sum + r.incomplete.length, 0),
    results
  });
  await context.close();
}

const total = runs.reduce((sum, r) => sum + r.total_violations, 0);
const report = {
  tool: "axe-core",
  axe_version: axeVersion,
  standard: "WCAG 2.2 AA",
  tags: WCAG_TAGS,
  page: "ui/dist/index.html",
  generated_at: new Date().toISOString(),
  screens_per_origin: SCREENS.length,
  total_violations: total,
  violations_by_impact: runs.flatMap((r) => r.results).flatMap((r) => r.violations)
    .reduce((acc, v) => { acc[v.impact || "unknown"] = (acc[v.impact || "unknown"] || 0) + 1; return acc; }, {}),
  incomplete_note:
    "Over file:// Chromium blocks axe-core from reading the stylesheet, so colour-contrast is " +
    "reported as incomplete (unknown) rather than passing. The http:// run reads the same CSS " +
    "and gives the real contrast verdict; compare the two blocks below.",
  page_errors: consoleErrors,
  runs
};
writeFileSync(resolve(uiDir, "axe-report.json"), JSON.stringify(report, null, 1) + "\n");

console.log(`\ntotal violations: ${total} across ${runs.length} origin(s) x ${SCREENS.length} screens`);
if (consoleErrors.length) console.log(`page errors: ${consoleErrors.length}\n  ${consoleErrors.join("\n  ")}`);
console.log("written: ui/axe-report.json");

await browser.close();
staticServer.close();
process.exit(total === 0 ? 0 : 1);
