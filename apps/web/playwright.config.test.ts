import { tmpdir } from "node:os";
import { describe, expect, it } from "vitest";

import config from "./playwright.config";

describe("Playwright configuration", () => {
  it("uses the operating system temporary directory for its database", () => {
    const servers = Array.isArray(config.webServer)
      ? config.webServer
      : [config.webServer];
    const apiCommand = servers[0]?.command ?? "";

    expect(apiCommand).toContain(tmpdir());
    expect(apiCommand).not.toContain("/private/tmp");
  });
});
