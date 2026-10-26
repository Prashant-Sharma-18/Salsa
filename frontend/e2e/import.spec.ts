import { expect, test } from "@playwright/test";

test("owner previews and imports a customer CSV", async ({ page }) => {
  const stamp = Date.now();
  const csv = [
    "Name,Email,Phone,Birthday,Points",
    `Import Alpha,alpha.${stamp}@example.com,,04-12,120`,
    `Import Beta,beta.${stamp}@example.com,(503) 555-0142,,`,
    `Import Broken,not-an-email,,,`,
  ].join("\n");

  await page.goto("/signin");
  await page.getByRole("button", { name: "Demo owner" }).click();
  await page.getByRole("navigation").getByRole("link", { name: "Customers" }).click();
  await page.getByRole("link", { name: "Import CSV" }).click();

  await page.setInputFiles("#import-file", { name: "customers.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Preview import" }).click();
  await expect(page.getByText("'not-an-email' is not a valid email")).toBeVisible();
  await expect(page.getByRole("button", { name: /Import 2 customers/ })).toBeDisabled();
  await page.screenshot({ path: "e2e/output/import-errors.png", fullPage: true });

  // Fix the file and import.
  await page.setInputFiles("#import-file", {
    name: "customers-fixed.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv.split("\n").slice(0, 3).join("\n")),
  });
  await page.getByRole("button", { name: "Preview import" }).click();
  await expect(page.getByText("First customers to be added")).toBeVisible();
  await page.getByRole("button", { name: /Import 2 customers/ }).click();
  await expect(page.getByRole("heading", { name: "Imported 2 customers" })).toBeVisible();

  await page.getByRole("link", { name: "View customers" }).click();
  await page.getByLabel("Search").fill(`alpha.${stamp}`);
  await expect(page.getByRole("link", { name: "Import Alpha" })).toBeVisible();
});
