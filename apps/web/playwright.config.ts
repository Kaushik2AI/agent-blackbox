import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against a RUNNING stack (`make dev`) with seeded data (`make seed-demo`).
 * `make test-e2e` does both checks for you. E2E_BASE_URL may include a proxy prefix; it
 * must end with "/" and tests navigate with relative paths.
 */
const base = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.WEB_PORT ?? "3000"}/`;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: base.endsWith("/") ? base : `${base}/`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
    // Optional: use an already-installed Chromium instead of `make e2e-install`.
    launchOptions: process.env.E2E_CHROMIUM_PATH
      ? { executablePath: process.env.E2E_CHROMIUM_PATH }
      : {},
  },
});
