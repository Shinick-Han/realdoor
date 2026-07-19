import { chromium } from "playwright";
const OUT = "C:/Users/jcpuk/source/hacknation-cmd/assets/video/team";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport:{width:1280,height:720}, recordVideo:{dir:OUT, size:{width:1280,height:720}} });
const p = await ctx.newPage();
const w = ms => p.waitForTimeout(ms);
const next = async () => { await p.locator("#step-next").click(); await w(500); };

// 13–30  what the product does, and why it shows its work
await p.goto("https://shinick-realdoor.hf.space/", { waitUntil:"networkidle" }); await w(2600);
await p.locator("button", { hasText: "Open the example file" }).first().click(); await w(2600);
await p.locator("#documents-body button", { hasText: "person_name" }).first().click(); await w(2400);
await p.mouse.wheel(0, 400); await w(2600);

// extraction
await p.locator("#documents-body button", { hasText: "household_size" }).first().click(); await w(2400);
// the rules engine
await p.locator("#ask-input").fill("what date did the current income limits take effect");
await p.locator("#ask-body button, #ask-dock button").filter({ hasText: "Ask" }).first().click(); await w(3600);
await p.mouse.wheel(0, 320); await w(2600);
// the interface
await next(); await w(2200);
await next(); await next(); await w(2400);
await p.mouse.wheel(0, 380); await w(2600);
// the harness that grades all of it
await p.locator("#go-how").click(); await w(1600);
await p.mouse.wheel(0, 900); await w(2800);
await p.mouse.wheel(0, 600); await w(2800);
await p.mouse.wheel(0, 550); await w(2800);
await p.mouse.wheel(0, 550); await w(3000);
await ctx.close(); await b.close();
