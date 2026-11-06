import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.js",
  workers: 1,
  retries: 0,
  use: {
    browserName: "chromium",
    headless: true,
    viewport: { width: 1512, height: 1100 },
  },
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
});
