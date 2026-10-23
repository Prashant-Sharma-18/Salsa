import { defineConfig } from "@playwright/test";

// Runs against the Flask server serving the built frontend (see README > End-to-end tests).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000",
    // Locally use the installed Chrome; in CI use Playwright's bundled Chromium.
    channel: process.env.CI ? undefined : (process.env.E2E_BROWSER_CHANNEL ?? "chrome"),
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
});
