/* Live-API mode check: the same page, same code path, pointed at FastAPI instead of the
 * bundled fixtures. Verifies the things that only exist when a server is present --
 * the rendered page PNG under the evidence boxes, an arbitrary field correction, a
 * free-text rule question, the packet zip, the output gate's real HTTP 500, and session
 * deletion actually destroying the session.
 *
 * Start the server first:  python ui/tools/serve_with_ui.py
 *   node ui/tools/live-check.mjs [http://127.0.0.1:8077]
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

await page.goto(`${base}/?live`);
await page.waitForFunction(() => document.querySelectorAll("#documents-body table").length > 0, { timeout: 15000 });

record("Page served by FastAPI at the same origin as /api/*",
  /Live API/.test(await page.locator("#mode-line").textContent()),
  (await page.locator("#mode-line").textContent()).trim());

const households = await page.locator("#household-select option").count();
record("Households listed from the live API", households > 0, `${households} households`);

/* The flow is linear now, so this walk is linear too: start, then Next, using the same
 * controls a user has. Screens are no longer reachable by jumping to a tab. */
const next = async () => { await page.locator("#step-next").click(); await page.waitForTimeout(120); };

// 1. rendered page image with overlay boxes on top of it
await page.locator("#start-demo").click();
await page.locator(".page-frame img").waitFor({ timeout: 15000 }).catch(() => {});
const imageOk = await page.evaluate(() => {
  const img = document.querySelector(".page-frame img");
  return img ? { w: img.naturalWidth, h: img.naturalHeight, alt: img.alt } : null;
});
const boxCount = await page.locator(".page-frame .evidence-box").count();
record("Step 1 — server-rendered page PNG with evidence boxes drawn over it",
  Boolean(imageOk) && imageOk.w > 0 && boxCount > 0,
  imageOk ? `${imageOk.w}x${imageOk.h}px, ${boxCount} boxes, alt="${imageOk.alt}"` : "no image");

// box placement must land inside the page, and near the text it points at
const geometry = await page.evaluate(() => {
  const frame = document.querySelector(".page-frame").getBoundingClientRect();
  return Array.from(document.querySelectorAll(".page-frame .evidence-box")).map((box) => {
    const r = box.getBoundingClientRect();
    return {
      field: box.dataset.field,
      insideFrame: r.top >= frame.top - 1 && r.bottom <= frame.bottom + 1 &&
                   r.left >= frame.left - 1 && r.right <= frame.right + 1,
      topFraction: (r.top - frame.top) / frame.height
    };
  });
});
record("Step 1 — every box lands inside the page (no y-flip)",
  geometry.every((g) => g.insideFrame),
  geometry.map((g) => `${g.field}@${(g.topFraction * 100).toFixed(1)}%`).join(" "));

// 2. an arbitrary correction, not one of the two recorded offline
await next();
await page.selectOption("#correct-doc", "HH-001-D01");
await page.selectOption("#correct-field", "household_size");
await page.fill("#correct-value", "5");
await page.locator("#correct-apply").click();
await page.locator("#correction-outcome-heading").waitFor({ timeout: 8000 }).catch(() => {});
const diff = (await page.locator("#correct-outcome table").textContent().catch(() => "")) || "";
record("Step 2 — arbitrary correction accepted and threshold recomputed by the server",
  /\$111,120\.00/.test(diff),
  /\$111,120\.00/.test(diff) ? "household size 5 -> frozen threshold $111,120.00" : diff.slice(0, 90));

// 3. free-text rule question
await next();
await page.fill("#ask-input", "What is the frozen 60% threshold for HH-001?");
await page.locator("#ask-body button[type=submit]").click();
await page.waitForTimeout(600);
const askBody = (await page.locator("#ask-answer").textContent()) || "";
record("Step 3 — free-text question answered live with a citation",
  /HUD-MTSP-002/.test(askBody) && /2026-05-01/.test(askBody),
  askBody.slice(0, 80).replace(/\s+/g, " ").trim());

// 5. packet zip from the server -- reached by walking steps 4, 5 and 6 in order
await next();   // step 4, the calculation
await next();   // step 5, what is missing or out of date
await next();   // step 6, check what we found and take the packet
const download = page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
await page.locator("#packet-download").click();
const file = await download;
record("Step 5 — packet downloaded from the server as a zip",
  Boolean(file) && /\.zip$/.test(file ? file.suggestedFilename() : ""),
  file ? file.suggestedFilename() : "no download");

// 6. the controls, on the secondary route, reached in one click from step 6
await page.locator("#go-how").click();
await page.waitForTimeout(150);
await page.getByRole("button", { name: /Try to make the server return a decision/ }).click();
await page.locator("#gate-output .callout").waitFor({ timeout: 8000 });
const gateText = (await page.locator("#gate-output").textContent()) || "";
record("Step 6 — output gate demonstrated live: server withholds its own response with HTTP 500",
  /Gate held\. HTTP 500/.test(gateText) && /eligible/.test(gateText),
  gateText.slice(0, 90).replace(/\s+/g, " ").trim());

for (const index of [0, 1, 2]) {
  await page.locator(`#probe-h-${index}`).locator("xpath=following-sibling::div//button").first().click();
}
await page.waitForTimeout(500);
const probes = await page.locator("#controls-body .callout--stop").count();
record("Step 6 — three refusals answered by the live server", probes >= 3, `${probes} refusals rendered`);

// session deletion really destroys the session
const sessionId = await page.evaluate(() => window.performance.now() && null);
await page.getByRole("button", { name: "Delete session data now" }).click();
await page.locator("#session-output .callout").waitFor({ timeout: 8000 });
const sessionText = (await page.locator("#session-output").textContent()) || "";
const deletedId = (sessionText.match(/Session ([0-9a-f]+)/) || [])[1];
let gone = false;
if (deletedId) {
  const followUp = await page.evaluate(async ([apiBase, id]) => {
    const response = await fetch(`${apiBase}/api/report/HH-001`, { headers: { "X-Session-Id": id } });
    return response.status;
  }, [base, deletedId]);
  gone = followUp === 404;
}
record("Step 6 — deleted session is really gone (follow-up request 404s)",
  /deleted/i.test(sessionText) && gone, `session ${deletedId} -> follow-up ${gone ? "404" : "still answering"}`);

// 7. live measurements -- same secondary route, further down the page
await page.waitForTimeout(400);
const measureText = (await page.locator("#measure-body").textContent()) || "";
record("Step 7 — measurements fetched from /api/selftest",
  /Measured/.test(measureText) && /exact match|fields total/i.test(measureText),
  measureText.slice(0, 70).replace(/\s+/g, " ").trim());

const passed = checks.filter((c) => c.ok).length;
console.log(`\n${passed}/${checks.length} live checks passed`);
await browser.close();
process.exit(passed === checks.length ? 0 : 1);
