// Captures key screens for visual review: node e2e/ui-shots.mjs <outdir>
import { chromium } from "@playwright/test";
const out = process.argv[2] ?? "e2e/output/ui";
const base = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000";
const browser = await chromium.launch({ channel: "chrome" });

async function shoot(viewport, prefix) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  await page.goto(base + "/signin");
  await page.screenshot({ path: `${out}/${prefix}-signin.png` });
  await page.getByRole("button", { name: "Demo owner" }).click();
  await page.waitForSelector("h1");
  await page.waitForTimeout(800);
  const res = await page.request.get(base + "/api/v1/customers?q=Ava");
  const cid = (await res.json()).data[0].id;
  for (const [name, path] of [["dashboard", "/"], ["customers", "/customers"], ["customer", `/customers/${cid}`], ["checkout", `/checkout?customer=${cid}`], ["rewards", "/rewards"], ["analytics", "/analytics"], ["billing", "/settings/billing"]]) {
    await page.goto(base + path);
    await page.waitForSelector("h1");
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${out}/${prefix}-${name}.png`, fullPage: prefix === "desk" });
  }
  await ctx.close();
}
await shoot({ width: 1366, height: 820 }, "desk");
await shoot({ width: 390, height: 844 }, "mob");
// customer-facing join page
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
const p = await ctx.newPage();
await p.goto(base + "/join/maple-street-coffee-demo");
await p.waitForTimeout(900);
await p.screenshot({ path: `${out}/mob-join.png`, fullPage: true });
await browser.close();
console.log("done");
