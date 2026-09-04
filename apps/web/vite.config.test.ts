import { describe, expect, it } from "vitest";

import viteConfig from "./vite.config";

describe("Vite development server", () => {
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
