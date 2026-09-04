import { defineConfig, devices } from "@playwright/test";
import { join } from "node:path";
import { tmpdir } from "node:os";

const desktop = devices["Desktop Chrome"];
const testDatabasePath = join(tmpdir(), "grounded-tutor-task11.db");
const testDatabaseUrl = `sqlite:///${testDatabasePath}`;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    ...desktop,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `rm -f ${JSON.stringify(testDatabasePath)} && DATABASE_URL=${JSON.stringify(testDatabaseUrl)} .venv/bin/alembic -c apps/api/alembic.ini upgrade head && DATABASE_URL=${JSON.stringify(testDatabaseUrl)} EXTERNAL_MODE=fake .venv/bin/uvicorn grounded_tutor.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000`,
      cwd: "../..",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173",
      cwd: ".",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "VITE_APP_MODE=demo_read_only npm run dev -- --host 127.0.0.1 --port 4174",
      cwd: ".",
      url: "http://127.0.0.1:4174",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
  projects: [
    { name: "local-1280x720", use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1280, height: 720 } } },
    { name: "local-1440x900", use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1440, height: 900 } } },
    { name: "demo-1280x720", use: { baseURL: "http://127.0.0.1:4174", viewport: { width: 1280, height: 720 } } },
    { name: "demo-1440x900", use: { baseURL: "http://127.0.0.1:4174", viewport: { width: 1440, height: 900 } } },
  ],
});
