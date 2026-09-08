import { afterEach, describe, expect, it, vi } from "vitest";

import viteConfig from "./vite.config";

describe("Vite development server", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("supports a server-only test backend override", async () => {
    vi.stubEnv("API_PROXY_TARGET", "http://127.0.0.1:8018");
    vi.resetModules();
    const { default: config } = await import("./vite.config");
    expect(config).toMatchObject({ server: { proxy: { "/api": "http://127.0.0.1:8018" } } });
  });

  it("proxies API requests to the local backend", () => {
    expect(viteConfig).toMatchObject({
      server: {
        proxy: {
          "/api": "http://127.0.0.1:8000",
        },
      },
    });
  });
});
