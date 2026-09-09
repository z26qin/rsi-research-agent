import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1536, height: 1024 },
    deviceScaleFactor: 1,
  },
  workers: 1,
  reporter: "list",
});
