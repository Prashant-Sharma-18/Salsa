import { expect, test, type Page } from "@playwright/test";

function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("status of 4")) errors.push(msg.text());
  });
  return errors;
}

async function demoLogin(page: Page, role: "owner" | "manager" | "staff") {
  await page.goto("/signin");
  await page.getByRole("button", { name: `Demo ${role}` }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Welcome/ })).toBeVisible();
}

test("owner can visit every main page without runtime errors", async ({ page }) => {
  const errors = trackErrors(page);
  await demoLogin(page, "owner");
  const pages: [string, string][] = [
    ["Customers", "Customers"],
    ["Rewards", "Rewards catalog"],
    ["Referrals", "Referrals"],
    ["Analytics & exports", "Analytics & exports"],
    ["Program settings", "Program settings"],
    ["Locations", "Locations"],
    ["Staff & permissions", "Staff & permissions"],
    ["Audit log", "Audit log"],
    ["Account & privacy", "Account & privacy"],
    ["Validate redemption", "Validate redemption"],
    ["Record purchase", "Record purchase"],
  ];
  for (const [link, heading] of pages) {
    await page.getByRole("navigation").getByRole("link", { name: link }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
  await page.screenshot({ path: "e2e/output/owner-checkout.png", fullPage: true });
  await page.getByRole("navigation").getByRole("link", { name: "Dashboard" }).click();
  await page.screenshot({ path: "e2e/output/owner-dashboard.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("staff purchase and redemption journey", async ({ page }) => {
  const errors = trackErrors(page);
  await demoLogin(page, "staff");
  await expect(page.getByRole("link", { name: "Program settings" })).toHaveCount(0);

  await page.getByRole("navigation").getByRole("link", { name: "Record purchase" }).click();
  await page.getByLabel("Find customer").fill("Ava");
  await page.getByRole("button", { name: /Ava Thompson/ }).click();
  const before = Number((await page.locator(".result-panel .stat-value").innerText()).replace(/,/g, ""));
  await page.getByLabel("Purchase total ($)").fill("45.00");
  await page.getByRole("button", { name: "Award points" }).click();
  await expect(page.getByText("Purchase recorded")).toBeVisible();
  await expect(page.getByText("Awarded 450 points.")).toBeVisible();
  await expect(page.locator(".result-panel .stat-value")).toHaveText((before + 450).toLocaleString("en-US"));

  await page.getByRole("radio", { name: /Free drip coffee/ }).check();
  await page.getByRole("button", { name: "Issue redemption code" }).click();
  const code = (await page.locator(".code-display").innerText()).trim();
  expect(code).toMatch(/^[A-Z0-9]{8}$/);

  await page.getByRole("navigation").getByRole("link", { name: "Validate redemption" }).click();
  await page.getByLabel("Redemption code").fill(code);
  await page.getByRole("button", { name: "Look up code" }).click();
  await page.getByRole("button", { name: "Mark as used" }).click();
  await expect(page.getByText("Redemption completed.")).toBeVisible();
  await page.screenshot({ path: "e2e/output/staff-redemption.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("owner enrolls a customer with validation feedback", async ({ page }) => {
  await demoLogin(page, "owner");
  await page.getByRole("link", { name: "Enroll customer" }).first().click();
  await page.getByRole("button", { name: "Enroll customer" }).click();
  await expect(page.getByText("Required").first()).toBeVisible();
  const email = `e2e.${Date.now()}@example.com`;
  await page.getByLabel("Name", { exact: true }).fill("Playwright Pat");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Enroll customer" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Playwright Pat" })).toBeVisible();
  await expect(page.getByText("Customer enrolled.")).toBeVisible();
});

test("mobile layout has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await demoLogin(page, "owner");
  for (const path of ["/", "/customers", "/checkout", "/analytics"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, path).toBeLessThanOrEqual(1);
  }
  await page.goto("/");
  await page.screenshot({ path: "e2e/output/mobile-dashboard.png", fullPage: true });
});
