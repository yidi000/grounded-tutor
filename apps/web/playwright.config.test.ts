import { tmpdir } from "node:os";
import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";

import config from "./playwright.config";

describe("Playwright configuration", () => {
  it("isolates every test server from the live backend", () => {
    const servers = Array.isArray(config.webServer) ? config.webServer : [config.webServer];
    expect(servers[0]?.url).toBe("http://127.0.0.1:8018/api/health");
    expect(servers[0]?.command).toContain("--port 8018");
    for (const server of servers) {
      expect(server?.reuseExistingServer).toBe(false);
      expect(server?.command).not.toMatch(/\b8000\b/);
    }
    for (const server of servers.slice(1)) {
      expect(server?.command).toContain("API_PROXY_TARGET=http://127.0.0.1:8018");
    }
  });

  it("keeps browser test API setup on the configured test origin", () => {
    const directory = `${process.cwd()}/tests/`;
    for (const file of readdirSync(directory).filter((name) => name.endsWith(".spec.ts"))) {
      expect(readFileSync(`${directory}${file}`, "utf8")).not.toMatch(/https?:\/\/(?:127\.0\.0\.1|localhost):8000/);
    }
  });

  it("uses the operating system temporary directory for its database", () => {
    const servers = Array.isArray(config.webServer)
      ? config.webServer
      : [config.webServer];
    const apiCommand = servers[0]?.command ?? "";

    expect(apiCommand).toContain(tmpdir());
    expect(apiCommand).not.toContain("/private/tmp");
  });
});
