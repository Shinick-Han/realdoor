/**
 * reflow-check.mjs — WCAG 2.2 AA SC 1.4.10 Reflow 검사.
 *
 * 왜 따로 있는가: axe-core 는 뷰포트를 바꾸지 않는다. 우리 axe 스캔은 1280x900 한 폭에서만
 * 돌았고, 그래서 "0 violations" 는 **데스크탑 폭에서 0건**이라는 뜻이었다. 리플로우는
 * 원리적으로 axe 의 탐지 대상이 아니므로, 재지 않으면 영원히 안 보인다.
 *
 * SC 1.4.10 (Level AA): 세로 스크롤 콘텐츠는 **320 CSS 픽셀** 폭에서 양방향 스크롤 없이
 * 제공되어야 한다. 320 은 임의의 숫자가 아니라 조항이 지정한 값이다(1280px 를 400%
 * 확대한 폭). 표·다이어그램처럼 2차원 배치가 본질적으로 필요한 콘텐츠는 예외이며,
 * 그런 요소는 자기 컨테이너 안에서만 가로 스크롤해야 한다.
 *
 *   node ui/tools/reflow-check.mjs [baseUrl]
 *
 * baseUrl 없으면 file:// 로 ui/dist/index.html 을 연다.
 */
import { chromium } from "playwright";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.resolve(HERE, "..", "dist", "index.html");

const base = process.argv[2] || pathToFileURL(DIST).href;

// 320 은 조항이 지정한 기준값. 나머지는 흔한 실기기 폭으로, 320 만 통과하고 그 사이에서
// 깨지는 경우를 잡기 위해 함께 잰다.
const WIDTHS = [320, 360, 390, 412, 768];

const SCREENS = [
  "screen-start", "screen-1", "screen-2", "screen-3",
  "screen-4", "screen-5", "screen-6", "screen-how",
];

const browser = await chromium.launch();
const failures = [];
let checks = 0;

for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 800 } });
  const page = await context.newPage();
  await page.goto(base, { waitUntil: "load" });
  await page.waitForTimeout(400);

  for (const screen of SCREENS) {
    // 화면 전환은 앱의 라우팅을 쓰지 않고 직접 토글한다. 이 검사의 대상은 레이아웃이지
    // 내비게이션이 아니며, 클릭 경로에 의존하면 한 화면이 막힐 때 나머지가 조용히 안 재진다.
    await page.evaluate((id) => {
      document.querySelectorAll(".screen").forEach((s) => { s.hidden = s.id !== id; });
    }, screen);
    await page.waitForTimeout(120);

    const result = await page.evaluate((vw) => {
      const doc = document.documentElement;
      const offenders = [];
      // 자기 컨테이너 안에서 가로 스크롤하는 요소는 조항이 허용한다. 그런 조상을 가진
      // 요소는 위반으로 세지 않는다.
      const scrollsItsOwn = (el) => {
        for (let n = el; n && n !== doc; n = n.parentElement) {
          const ov = getComputedStyle(n).overflowX;
          if (ov === "auto" || ov === "scroll") return true;
        }
        return false;
      };
      for (const el of document.querySelectorAll("body *")) {
        if (el.hidden || !el.getClientRects().length) continue;
        const r = el.getBoundingClientRect();
        if (r.right <= vw + 1) continue;
        if (scrollsItsOwn(el)) continue;
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || "").toString().trim().split(/\s+/)[0] || "",
          right: Math.round(r.right),
        });
      }
      return {
        scrollWidth: doc.scrollWidth,
        horizontal: doc.scrollWidth > vw + 1,
        offenders: offenders.slice(0, 6),
      };
    }, width);

    checks++;
    if (result.horizontal || result.offenders.length) {
      failures.push({ width, screen, ...result });
    }
  }

  await context.close();
}

await browser.close();

console.log(`reflow: ${WIDTHS.length} widths x ${SCREENS.length} screens = ${checks} checks`);
if (!failures.length) {
  console.log("PASS  no horizontal scrolling at any tested width");
  process.exit(0);
}

console.log(`FAIL  ${failures.length} screen/width combinations overflow\n`);
for (const f of failures) {
  console.log(`  ${f.screen} @ ${f.width}px  scrollWidth=${f.scrollWidth}`);
  for (const o of f.offenders) {
    console.log(`      ${o.tag}${o.cls ? "." + o.cls : ""} → ${o.right}px`);
  }
}
process.exit(1);
