import { expect, test } from "@playwright/test";

test("owner prints a counter sign with a scannable join QR code", async ({ page }) => {
  await page.goto("/signin");
  await page.getByRole("button", { name: "Demo owner" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Program settings" }).click();
  await page.getByRole("link", { name: "Print counter sign" }).click();
  await expect(page.getByRole("heading", { name: "Join Maple Rewards" })).toBeVisible();
  const qr = page.getByAltText(/QR code linking to/);
  await expect(qr).toBeVisible();
  // The image actually loaded (not a broken image).
  expect(await qr.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: "e2e/output/counter-sign.png", fullPage: true });
});
