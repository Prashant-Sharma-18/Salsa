import { expect, test } from "@playwright/test";

test("platform admin suspends and reinstates a business", async ({ page, browser }) => {
  await page.goto("/signin");
  await page.getByRole("button", { name: "Demo admin" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Platform admin" })).toBeVisible();
  await page.getByLabel("Search").fill("maple");
  await page.getByRole("button", { name: /Manage Maple Street Coffee/ }).click();

  await page.getByLabel("Reason (required, audit-logged)").fill("E2E suspension check");
  await page.getByRole("button", { name: "Suspend business" }).click();
  await expect(page.getByText("Business suspended.")).toBeVisible();
  await page.screenshot({ path: "e2e/output/admin-console.png", fullPage: true });

  // A merchant user now sees the suspension screen.
  const merchant = await browser.newPage();
  await merchant.goto("/signin");
  await merchant.getByRole("button", { name: "Demo owner" }).click();
  await expect(merchant.getByText("This business account is suspended")).toBeVisible();

  await page.getByLabel("Reason (required, audit-logged)").fill("E2E reinstate");
  await page.getByRole("button", { name: "Reinstate business" }).click();
  await expect(page.getByText("Business reinstated.")).toBeVisible();
  await merchant.reload();
  await expect(merchant.getByRole("heading", { level: 1, name: /Welcome/ })).toBeVisible();
});
