import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../api/types";
import { Composer } from "../../components/composer";
import { renderChatApp } from "../../test/render-chat-app";

const groundedResponse: ChatResponse = {
  conversation_id: "00000000-0000-4000-8000-000000000010",
  message_id: "00000000-0000-4000-8000-000000000011",
  status: "ok",
  answer_blocks: [
    {
      id: "block-1",
      kind: "answer",
      text: "The mean describes the average value.",
      citation_ids: ["citation-1"],
    },
  ],
  citations: [
    {
      id: "citation-1",
      source_id: "00000000-0000-4000-8000-000000000002",
      source_name: "Week 1 notes",
      source_version: 1,
      chunk_id: "chunk-18",
      excerpt: "Mean is an average.",
      context_before: "Measures of center summarize a distribution.",
      context_after: null,
      locator: { kind: "pdf", page: 3, section: "Measures of center" },
    },
  ],
  suggested_actions: [],
};

const insufficientMaterialResponse: ChatResponse = {
  conversation_id: "00000000-0000-4000-8000-000000000010",
  message_id: "00000000-0000-4000-8000-000000000012",
  status: "insufficient_material",
  answer_blocks: [],
  citations: [],
  suggested_actions: [{ type: "add_material" }, { type: "rephrase" }],
};

describe("ChatView", () => {
  it("opens the cited source for the selected answer block and restores focus", async () => {
    const user = userEvent.setup();
    renderChatApp(groundedResponse);

    const anchor = screen.getByRole("button", {
      name: "引用 1：Week 1 notes",
    });
    await user.click(anchor);

    const context = screen.getByRole("complementary", { name: "上下文" });
    expect(context).toHaveTextContent("Week 1 notes");
    expect(context).toHaveTextContent("Mean is an average.");
    expect(screen.getByText("第 3 页 · Measures of center")).toBeVisible();
    expect(screen.getByText("命中片段")).toBeVisible();
    expect(screen.getByText("The mean describes the average value.").closest("article")).toHaveClass("answer-block-selected");

    await user.click(screen.getByRole("button", { name: "关闭引用详情" }));
    expect(anchor).toHaveFocus();
  });

  it("renders insufficient material as a normal chat state", () => {
    renderChatApp(insufficientMaterialResponse);

    expect(screen.getByText("当前资料不足以支持这个答案")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加相关资料" })).toBeVisible();
    expect(screen.getByRole("button", { name: "换一种问法" })).toBeVisible();
  });

  it("numbers unique citations per assistant message and hides missing IDs", () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    renderChatApp({
      ...groundedResponse,
      answer_blocks: [
        {
          id: "block-2",
          kind: "answer",
          text: "A second supported point.",
          citation_ids: ["missing-citation", "citation-1"],
        },
      ],
    });

    expect(screen.getByRole("button", { name: "引用 1：Week 1 notes" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "引用 2：Week 1 notes" })).not.toBeInTheDocument();
    expect(screen.queryByText("missing-citation")).not.toBeInTheDocument();
    expect(warning).toHaveBeenCalledWith("Missing citation for answer block", "block-2", "missing-citation");
  });

  it("keeps focus on the Sources tab when dismissing citation detail", async () => {
    const user = userEvent.setup();
    renderChatApp(groundedResponse);
    await user.click(screen.getByRole("button", { name: "引用 1：Week 1 notes" }));

    const sourcesTab = screen.getByRole("button", { name: "全部资料" });
    await user.click(sourcesTab);
    await new Promise((resolve) => window.setTimeout(resolve, 1));

    expect(screen.getByText("资料列表")).toBeVisible();
    expect(sourcesTab).toHaveFocus();
  });

  it("restarts numbering and highlights only the owning block across messages", async () => {
    const user = userEvent.setup();
    const second: ChatResponse = {
      ...groundedResponse,
      message_id: "00000000-0000-4000-8000-000000000012",
      answer_blocks: [{ ...groundedResponse.answer_blocks[0], text: "A later answer." }],
      citations: [{ ...groundedResponse.citations[0], source_name: "Week 2 notes" }],
    };
    renderChatApp([
      { question: "First question", response: groundedResponse },
      { question: "Second question", response: second },
    ]);

    expect(screen.getByRole("button", { name: "引用 1：Week 1 notes" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "引用 1：Week 2 notes" }));
    const selected = document.querySelectorAll(".answer-block-selected");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("A later answer.");
  });
});

describe("Composer", () => {
  it("sends ASK only when a ready source exists", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(async () => undefined);
    const { rerender } = render(
      <Composer mode="local" ready={false} onSubmit={onSubmit} />,
    );

    expect(screen.getByLabelText("向资料提问")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();

    rerender(<Composer mode="local" ready onSubmit={onSubmit} />);
    await user.type(screen.getByLabelText("向资料提问"), "What is a mean?");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(onSubmit).toHaveBeenCalledWith("What is a mean?");
    expect(screen.getByLabelText("向资料提问")).toHaveValue("");
  });

  it("preserves the draft through a retriable ASK error", async () => {
    const user = userEvent.setup();
    render(
      <Composer
        mode="local"
        ready
        onSubmit={vi.fn(async () => {
          throw new Error("private provider details");
        })}
      />,
    );

    const input = screen.getByLabelText("向资料提问");
    await user.type(input, "What is a mean?");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("当前无法完成提问，请保留内容后重试。");
    expect(input).toHaveValue("What is a mean?");
    expect(screen.queryByText("private provider details")).not.toBeInTheDocument();
  });
});
