import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { demoFixture } from "./demo/fixture";
import { AnswerBlock } from "./features/chat/answer-block";
import { CitationDetail } from "./features/chat/citation-detail";

it("renders hostile answer and source markup as text while citation selection still works", async () => {
  const markup = '<img src="https://attacker.invalid/steal" onerror="alert(1)"><script>fetch("/api/workspaces",{method:"DELETE"})</script><iframe src="https://attacker.invalid"></iframe>';
  const citation = {
    ...demoFixture.exchange.response.citations[0],
    source_name: markup,
    excerpt: markup,
    context_before: markup,
    context_after: markup,
    locator: { kind: "chunk" as const, label: markup },
  };
  const block = { ...demoFixture.exchange.response.answer_blocks[0], text: markup, citation_ids: [citation.id] };
  const onSelectCitation = vi.fn();
  const { container } = render(<>
    <AnswerBlock block={block} citationById={new Map([[citation.id, citation]])} citationNumbers={new Map([[citation.id, 1]])} selected={false} onSelectCitation={onSelectCitation} />
    <CitationDetail citation={citation} />
  </>);

  for (const selector of [".answer-block > p", ".evidence-anchor > span:last-child", ".citation-detail h2", ".citation-locator", ".citation-excerpt blockquote", ".citation-context p"]) {
    const elements = container.querySelectorAll(selector);
    expect(elements.length).toBeGreaterThan(0);
    for (const element of elements) expect(element.textContent).toBe(markup);
  }
  expect(container.querySelectorAll("img, script, iframe")).toHaveLength(0);
  const anchor = screen.getByRole("button", { name: `引用 1：${markup}` });
  await userEvent.click(anchor);
  expect(onSelectCitation).toHaveBeenCalledWith(citation, block.id, anchor);
});
