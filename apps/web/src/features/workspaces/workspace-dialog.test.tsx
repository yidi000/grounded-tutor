import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SourceIngestionCapabilities } from "../../api/types";
import { WorkspaceDialog } from "./workspace-dialog";

const capabilities: SourceIngestionCapabilities = {
  accepted_extensions: [".pdf"],
  max_upload_bytes: 20_000_000,
  settings: [],
  workspace_models: [
    { key: "vector_model", supported: true, disabled_reason: null },
    {
      key: "agent_model",
      supported: false,
      disabled_reason: "deployment_not_verified",
    },
  ],
  read_only_demo: false,
};

describe("WorkspaceDialog", () => {
  it("shows title first and only verified model controls in a collapsed section", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceDialog
        open
        capabilities={capabilities}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("主题名称")).toBeVisible();
    expect(screen.queryByLabelText("向量模型")).not.toBeInTheDocument();
    await user.click(screen.getByText("模型配置（高级）"));
    expect(screen.getByLabelText("向量模型")).toBeVisible();
    expect(screen.getByText(/更换后通常需要重新建立资料索引/)).toBeVisible();
    expect(screen.queryByLabelText("文本处理模型")).not.toBeInTheDocument();
  });

  it("omits blank model values and shows created choices read-only", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (_input, init?: RequestInit) => new Response(JSON.stringify({ id: "00000000-0000-4000-8000-000000000001", title: "统计学", source_count: 0, ready_source_count: 0, model_choices: { vector_model: "embed-v2", agent_model: null, vlm_model: null }, created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:00Z" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const props = { capabilities, onClose: vi.fn(), onCreated: vi.fn() };
    const { rerender } = render(<WorkspaceDialog open {...props} />);
    await user.type(screen.getByLabelText("主题名称"), "统计学");
    await user.click(screen.getByRole("button", { name: "模型配置（高级）" }));
    await user.type(screen.getByLabelText("向量模型"), "embed-v2");
    await user.click(screen.getByRole("button", { name: "创建主题" }));
    expect(await screen.findByText("主题已创建")).toBeVisible();
    expect(screen.getByText("embed-v2")).toBeVisible();
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({ title: "统计学", vector_model: "embed-v2" });
    expect(body).not.toHaveProperty("agent_model");
    rerender(<WorkspaceDialog open={false} {...props} />);
    rerender(<WorkspaceDialog open {...props} />);
    expect(screen.getByRole("heading", { name: "创建学习主题" })).toBeVisible();
    expect(screen.getByLabelText("主题名称")).toHaveValue("");
  });
});
