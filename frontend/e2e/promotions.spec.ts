import { expect, test } from "@playwright/test";

test("manager creates an every-day promotion and staff see it applied at checkout", async ({ page, browser }) => {
  const name = `E2E bonus ${Date.now()}`;
  await page.goto("/signin");
  await page.getByRole("button", { name: "Demo manager" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Promotions" }).click();
  await expect(page.getByText("Double Points Tuesdays")).toBeVisible(); // seeded
  await page.getByRole("button", { name: "New promotion" }).click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Type").selectOption("bonus");
  await page.getByLabel("Bonus points").fill("25");
  await page.getByRole("button", { name: "Create promotion" }).click();
  await expect(page.getByText("Promotion created.")).toBeVisible();

  const staff = await browser.newPage();
  await staff.goto("/signin");
  await staff.getByRole("button", { name: "Demo staff" }).click();
  await staff.getByRole("navigation").getByRole("link", { name: "Record purchase" }).click();
  await staff.getByLabel("Find customer").fill("Liam");
  await staff.getByRole("button", { name: /Liam Carter/ }).click();
  await expect(staff.getByText(`${name} (+25 bonus points)`, { exact: false })).toBeVisible();
  await staff.getByLabel("Purchase total ($)").fill("10.00");
  await staff.getByRole("button", { name: "Award points" }).click();
  await expect(staff.getByText(`${name} (+25)`, { exact: false })).toBeVisible();
  await staff.screenshot({ path: "e2e/output/checkout-promotion.png", fullPage: true });

  // Archive it again so repeated runs stay clean.
  await page.getByRole("button", { name: `Edit ${name}` }).click();
  await page.getByLabel("Status").selectOption("archived");
  await page.getByRole("button", { name: "Save promotion" }).click();
  await expect(page.getByText("Promotion updated.")).toBeVisible();
});
