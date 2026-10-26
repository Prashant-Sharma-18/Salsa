import { createHmac } from "node:crypto";
import { expect, test } from "@playwright/test";

/** RFC 6238 TOTP, the same algorithm an authenticator app uses. */
function totp(secretB32: string, offsetSeconds = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secretB32.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor((Date.now() / 1000 + offsetSeconds) / 30)));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

test("owner turns on two-factor and must use it to sign in", async ({ page }) => {
  const email = `mfa.${Date.now()}@example.com`;
  const password = "mfa-e2e-password-1";

  await page.goto("/signup");
  await page.getByLabel("Your name").fill("MFA Tester");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByLabel("Business name").fill("MFA Bakery");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Location name").fill("Main");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByLabel("Points per $1")).toBeVisible(); // step 3 must not be skipped
  await page.getByRole("button", { name: "Create program" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)/ })).toBeVisible();

  await page.getByRole("navigation").getByRole("link", { name: "Account & privacy" }).click();
  await page.getByRole("button", { name: "Set up two-factor" }).click();
  await expect(page.getByAltText("QR code for your authenticator app")).toBeVisible();
  await page.getByText("Can't scan? Enter this key instead").click();
  const secret = (await page.locator("details code").innerText()).trim();
  await page.getByLabel("Authentication code").fill(totp(secret));
  await page.getByRole("button", { name: "Turn on two-factor" }).click();
  await expect(page.getByText("Save your recovery codes now")).toBeVisible();
  await page.getByLabel("I have saved these codes somewhere safe").check();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("10 unused recovery codes.")).toBeVisible();
  await page.screenshot({ path: "e2e/output/mfa-enabled.png", fullPage: true });

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-factor verification" })).toBeVisible();
  await page.getByLabel("Authentication code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("That code is not valid")).toBeVisible();
  await page.getByLabel("Authentication code").fill(totp(secret, 30)); // next step: setup used the current one
  await page.getByRole("button", { name: "Verify" }).click();
  // Signed in: returned to the page they were on, with two-factor shown as on.
  await expect(page.getByRole("heading", { level: 1, name: "Account & privacy" })).toBeVisible();
  await expect(page.getByText("10 unused recovery codes.")).toBeVisible();
});
