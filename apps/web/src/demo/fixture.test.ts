import { afterEach, describe, expect, it, vi } from "vitest";
import { demoFixture } from "./fixture";

function expectFrozen(value: unknown): void {
  if (value !== null && typeof value === "object") {
    expect(Object.isFrozen(value)).toBe(true);
    Object.values(value).forEach(expectFrozen);
  }
}

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

describe("public demo fixture", () => {
  it("is versioned, recursively immutable and has resolvable citations", () => {
    expect(demoFixture.version).toBe("rag-demo-v1");
    expect(demoFixture.provenance.license).toBe("CC0-1.0");
    expectFrozen(demoFixture);
    const response = demoFixture.exchange.response;
    const ids = new Set(response.citations.map((citation) => citation.id));
    expect(ids.size).toBe(response.citations.length);
    for (const block of response.answer_blocks) {
      expect(block.citation_ids.length).toBeGreaterThan(0);
      expect(block.citation_ids.every((id) => ids.has(id))).toBe(true);
    }
    expect(() => { response.answer_blocks[0].text = "changed"; }).toThrow();
  });

  it("keeps the local setup link inside a repository base path", async () => {
    vi.stubEnv("BASE_URL", "/notebook/");
    const { demoFixture: nested } = await import("./fixture");
    expect(nested.localInstructionsUrl).toBe("/notebook/local-setup.html");
  });
});
