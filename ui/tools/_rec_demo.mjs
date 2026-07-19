import { chromium } from "playwright";
const OUT = "C:/Users/jcpuk/source/hacknation-cmd/assets/video/demo";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport:{width:1280,height:720}, recordVideo:{dir:OUT, size:{width:1280,height:720}} });
const p = await ctx.newPage();
const w = ms => p.waitForTimeout(ms);
const next = async () => { await p.locator("#step-next").click(); await w(600); };

// 0–8  the page opens holding nothing, then a file is opened
await p.goto("https://shinick-realdoor.hf.space/", { waitUntil:"networkidle" });
await w(4200);
await p.locator("button", { hasText: "Open the example file" }).first().click();
await w(3200);

// 8–20  step 1 — a value, and the box on the page it was read from
await p.locator("#documents-body button", { hasText: "person_name" }).first().click(); await w(2600);
await p.mouse.wheel(0, 380); await w(2600);
await p.locator("#documents-body button", { hasText: "household_size" }).first().click(); await w(2600);
await p.mouse.wheel(0, 420); await w(2600);

// 20–29  step 2 — a correction, and the numbers underneath moving
await next();
await p.locator("#correct-body button", { hasText: "Apply correction" }).first().click(); await w(4200);
await p.mouse.wheel(0, 400); await w(3200);

// 29–40  step 4 — formula, threshold, effective date; ask a rule from the pinned box
await next(); await next();
await p.mouse.wheel(0, 300); await w(3000);
await p.locator("#ask-input").fill("what date did the current income limits take effect");
await p.locator("#ask-body button, #ask-dock button").filter({ hasText: "Ask" }).first().click();
await w(4200);
await p.mouse.wheel(0, 350); await w(3200);

// 40–48  step 5 — what is missing or out of date
await next();
await w(3200); await p.mouse.wheel(0, 380); await w(3600);

// 48–55  step 6 — the packet
await next();
await w(3200); await p.mouse.wheel(0, 350); await w(3200);

// 55–60  the refusal, then rest on it
await p.locator("#ask-input").fill("am I eligible for this apartment");
await p.locator("#ask-body button, #ask-dock button").filter({ hasText: "Ask" }).first().click();
await w(4500);
await ctx.close(); await b.close();
