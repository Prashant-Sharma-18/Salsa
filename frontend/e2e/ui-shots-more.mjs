// Remaining screens for visual review: node e2e/ui-shots-more.mjs <outdir>
import { chromium } from "@playwright/test";
const out = process.argv[2] ?? "e2e/output/ui-more";
const base = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5003";
const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ viewport: { width: 1366, height: 820 } });
const page = await ctx.newPage();
await page.goto(base + "/signin");
await page.getByRole("button", { name: "Demo owner" }).click();
await page.waitForSelector("h1");
for (const [name, path] of [
  ["team", "/team"], ["locations", "/locations"], ["audit", "/audit"], ["settings", "/settings/program"],
  ["promotions", "/promotions"], ["referrals", "/referrals"], ["redemptions", "/redemptions"], ["account", "/account"],
  ["enroll", "/customers/new"], ["import", "/customers/import"],
]) {
  await page.goto(base + path);
  await page.waitForSelector("h1");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
}
await ctx.close();
const admin = await (await browser.newContext({ viewport: { width: 1366, height: 820 } })).newPage();
await admin.goto(base + "/signin");
await admin.getByRole("button", { name: "Demo admin" }).click();
await admin.waitForSelector("h1");
await admin.waitForTimeout(800);
await admin.screenshot({ path: `${out}/admin.png`, fullPage: true });
await browser.close();
console.log("done");
