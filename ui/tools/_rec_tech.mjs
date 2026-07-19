import { chromium } from "playwright";
const OUT = "C:/Users/jcpuk/source/hacknation-cmd/assets/video/tech";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport:{width:1280,height:720}, recordVideo:{dir:OUT, size:{width:1280,height:720}} });
const p = await ctx.newPage();
const w = ms => p.waitForTimeout(ms);
const next = async () => { await p.locator("#step-next").click(); await w(600); };

// 0–9  "not one that sounds certain — one whose answers you can check"
await p.goto("https://shinick-realdoor.hf.space/", { waitUntil:"networkidle" }); await w(3200);
await p.locator("button", { hasText: "Open the example file" }).first().click(); await w(3000);
await p.mouse.wheel(0, 420); await w(2600);

// 9–25  two models: ask in the renter's own words, classifier tier shows how it read you
await p.locator("#ask-input").fill("are they using the old numbers or the new ones right now");
await p.locator("#ask-body button, #ask-dock button").filter({ hasText: "Ask" }).first().click();
await w(4600);
await p.mouse.wheel(0, 300); await w(3800);
const tech = p.locator("#ask-answer summary").first();
if (await tech.count()) { await tech.click(); await w(3600); }

// 25–36  deterministic code and the organizer's own reference implementation
await next(); await next(); await next();
await w(2600); await p.mouse.wheel(0, 380); await w(3400);

// 36–48  the output gate blocking the server's own response, live
await p.locator("#go-how").click(); await w(1800);
const gate = p.locator("button", { hasText: "Try to make the server return a decision" }).first();
await gate.scrollIntoViewIfNeeded(); await w(1200);
await gate.click(); await w(4600);

// 48–59  the scorecard, including the number we did not like
await p.mouse.wheel(0, 600); await w(3600);
await p.mouse.wheel(0, 500); await w(3600);
await p.mouse.wheel(0, 500); await w(3600);
await p.mouse.wheel(0, 500); await w(3600);
await p.mouse.wheel(0, 500); await w(3800);
await ctx.close(); await b.close();
