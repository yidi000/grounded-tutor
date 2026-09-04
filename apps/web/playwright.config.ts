import { defineConfig, devices } from "@playwright/test";

const desktop = devices["Desktop Chrome"];

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
      command: "rm -f /private/tmp/grounded-tutor-task11.db && DATABASE_URL=sqlite:////private/tmp/grounded-tutor-task11.db .venv/bin/alembic -c apps/api/alembic.ini upgrade head && DATABASE_URL=sqlite:////private/tmp/grounded-tutor-task11.db EXTERNAL_MODE=fake .venv/bin/uvicorn grounded_tutor.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000",
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
