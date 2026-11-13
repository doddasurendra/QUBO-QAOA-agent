import { defineConfig, devices } from "@playwright/test";

const port = process.env.E2E_PORT ?? "8790";
// Playwright's pinned Chromium everywhere (`npx playwright install chromium`). An installed branded browser can
// be used with PW_CHANNEL=msedge|chrome, but the installed Edge crashed after file downloads in this suite.
const channel = process.env.PW_CHANNEL || undefined;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  fullyParallel: false,          // tests share one backend + DB; run in order
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [["list"], ["html", { outputFolder: "e2e/.report", open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    channel,
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "desktop", testMatch: /.*\.spec\.ts/, dependencies: ["setup"], use: { ...devices["Desktop Chrome"], channel } },
  ],
  webServer: {
    command: "node e2e/start-server.mjs",
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
