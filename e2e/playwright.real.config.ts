import { defineConfig } from "@playwright/test";

const baseURL = process.env.GOLDENDICT_E2E_URL?.trim();
if (!baseURL) {
  throw new Error(
    "GOLDENDICT_E2E_URL must point to a running demo backed by the real OALDPE fixture",
  );
}

export default defineConfig({
  testDir: ".",
  testMatch: "real-oaldpe.spec.ts",
  outputDir: "./.artifacts/real-test-results",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 150_000,
  expect: { timeout: 120_000 },
  reporter: process.env.CI
    ? [
        ["line"],
        ["html", { open: "never", outputFolder: "e2e/.artifacts/real-report" }],
      ]
    : "list",
  use: {
    baseURL,
    browserName: "chromium",
    channel: "chromium",
    colorScheme: "light",
    deviceScaleFactor: 1,
    locale: "en-US",
    screenshot: "only-on-failure",
    timezoneId: "UTC",
    trace: "retain-on-failure",
    viewport: { width: 2048, height: 1228 },
  },
});
