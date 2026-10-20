// Drives the real stack (web + API + Postgres) through the core flow and captures reference screenshots.
// Usage: node e2e/walkthrough.mjs <baseUrl> <outDir> <invite1> <invite2> <invite3>
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const [base = "http://localhost:3000", out = "screens", ...codes] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM ?? "/opt/pw-browsers/chromium" });
// E2E_SUFFIX lets a re-run against a database that already has these handles sign up fresh members.
const handles = ["andru", "kai", "mika"].map((h) => h + (process.env.E2E_SUFFIX ?? ""));
const names = ["Andru", "Kai", "Mika"];
const failures = [];
const check = (cond, msg) => {
  if (!cond) failures.push(msg);
  console.log(`${cond ? "PASS" : "FAIL"} ${msg}`);
};

async function noHScroll(page, label) {
  const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  check(sw <= cw, `${label}: no horizontal scroll (${sw} <= ${cw})`);
}

const contexts = [];
for (let i = 0; i < codes.length; i++) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => failures.push(`pageerror: ${e.message}`));
  await page.goto(`${base}/join?code=${codes[i]}`);
  await page.fill("#handle", handles[i]);
  await page.fill("#name", names[i]);
  await page.click("button:has-text('Join the league')");
  await page.waitForURL(`${base}/`);
  contexts.push({ ctx, page });
}

const { page } = contexts[0];
await page.waitForSelector(".mrow");
await page.waitForTimeout(800);
await page.screenshot({ path: `${out}/01-today-390.png` });
const firstOdds = page.locator(".mrow .side").first();
check(await firstOdds.isVisible(), "390: first match odds visible above the fold");
const box = await firstOdds.boundingBox();
check(box && box.y + box.height <= 844 - 64, `390: first odds tile within first viewport (bottom ${box && Math.round(box.y + box.height)})`);
await noHScroll(page, "today 390");

await firstOdds.click();
check((await firstOdds.getAttribute("aria-pressed")) === "true", "odds tile toggles aria-pressed");
await page.click(".slipbar");
await page.fill(".sheet .slip-line .stake-input input", "75");
await page.fill(".sheet .slip-line .stake-input input", "400");
await page.screenshot({ path: `${out}/02-slip-390.png` });
await page.click(".sheet button:has-text('Review picks')");
await page.waitForSelector(".sheet button:has-text('Place 1 pick')");
await page.click(".sheet button:has-text('Place 1 pick')");
await page.waitForSelector(".sheet h2:has-text('Picks placed')");
await page.screenshot({ path: `${out}/03-receipt-390.png` });
check((await page.locator(".sheet .notice.success").count()) === 1, "ticket accepted with receipt");
await page.keyboard.press("Escape");

// Second pick from the event detail page (draft tab if present).
await page.locator(".mrow .mrow-foot").first().click();
await page.waitForSelector(".scoreboard");
await page.waitForTimeout(500);
await page.screenshot({ path: `${out}/04-event-390.png`, fullPage: true });
await noHScroll(page, "event 390");

await page.goto(`${base}/picks`);
await page.waitForSelector(".pick");
await page.screenshot({ path: `${out}/05-picks-390.png` });

// Kai bets too, then everyone views the league.
const kai = contexts[1].page;
await kai.reload();
await kai.waitForSelector(".mrow .side");
await kai.locator(".mrow .side").nth(1).click();
await kai.click(".slipbar");
await kai.click(".sheet .presets button:has-text('25%')");
await kai.click(".sheet button:has-text('Review picks')");
await kai.click(".sheet button:has-text('Place 1 pick')");
await kai.waitForSelector(".sheet h2:has-text('Picks placed')");

await page.goto(`${base}/league`);
await page.waitForSelector(".standing");
await page.screenshot({ path: `${out}/06-league-390.png` });
check((await page.locator(".standing").count()) >= codes.length, "league lists every new member");
check((await page.locator(".pick").count()) === 0, "friends' open picks stay hidden before lock");

await page.goto(`${base}/explore?tab=FUTURES`);
await page.waitForSelector(".market");
await page.screenshot({ path: `${out}/07-futures-390.png` });

// Every screen at every width, full page. Match page builders are opened so the shot shows what a tap reveals.
await page.goto(`${base}/`);
await page.waitForSelector(".mrow .mrow-foot");
const matchPath = await page.locator(".mrow .mrow-foot").first().getAttribute("href");
const screens = [
  ["today", "/", ".mrow"],
  ["match", matchPath, ".scoreboard"],
  ["swiss", "/swiss", ".recrow"],
  ["picks", "/picks", ".pick"],
  ["league", "/league", ".standing"],
];
const signedIn = await contexts[0].ctx.storageState();
for (const width of [320, 390, 768, 1440]) {
  const ctx = await browser.newContext({ viewport: { width, height: width > 1024 ? 900 : 844 }, deviceScaleFactor: width > 1024 ? 1 : 2, storageState: signedIn });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => failures.push(`pageerror ${width}: ${e.message}`));
  for (const [i, [name, path, sel]] of screens.entries()) {
    await p.goto(`${base}${path}`);
    await p.waitForSelector(sel);
    if (name === "match") for (const s of await p.locator("details.builder > summary").all()) {
      if (!(await s.evaluate((el) => el.parentElement.open))) await s.click();
    }
    await p.waitForTimeout(600);
    await p.screenshot({ path: `${out}/${String(i + 11)}-${name}-${width}.png`, fullPage: true });
    await noHScroll(p, `${name} ${width}`);
  }
  await ctx.close();
}

const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, storageState: await contexts[0].ctx.storageState() });
const dp = await desk.newPage();
await dp.goto(`${base}/`);
await dp.waitForSelector(".mrow .side");
await dp.locator(".mrow .side").nth(2).click();
await dp.fill(".sliprail .slip-line .stake-input input", "250");
await dp.waitForTimeout(400);
await dp.screenshot({ path: `${out}/09-today-1440.png` });
await noHScroll(dp, "today 1440");
await dp.locator(".mrow .mrow-foot").first().click();
await dp.waitForSelector(".scoreboard");
await dp.waitForTimeout(400);
await dp.screenshot({ path: `${out}/10-event-1440.png` });

await browser.close();
if (failures.length) {
  console.error(`\n${failures.length} failure(s):\n` + failures.join("\n"));
  process.exit(1);
}
console.log("\nAll walkthrough checks passed.");
