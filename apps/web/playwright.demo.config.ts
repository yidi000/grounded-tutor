import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "demo-static.spec.ts",
  workers: 1,
  reporter: "line",
  use: { channel: "chrome", baseURL: "http://127.0.0.1:4175/grounded-demo/" },
  webServer: {
    command: "VITE_APP_MODE=demo_read_only VITE_PUBLIC_BASE_PATH=/grounded-demo/ npm run build && VITE_PUBLIC_BASE_PATH=/grounded-demo/ npm exec -- vite preview --host 127.0.0.1 --port 4175",
    cwd: ".",
    url: "http://127.0.0.1:4175/grounded-demo/",
    reuseExistingServer: false,
    timeout: 60_000,
  },
  projects: [
    { name: "static-demo-1280", use: { viewport: { width: 1280, height: 720 } } },
    { name: "static-demo-1440", use: { viewport: { width: 1440, height: 900 } } },
  ],
});
