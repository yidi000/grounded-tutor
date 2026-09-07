import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SourceIngestionCapabilities } from "../../api/types";
import { SourceWizard } from "./source-wizard";

const source = {
  id: "00000000-0000-4000-8000-000000000002",
  workspace_id: "00000000-0000-4000-8000-000000000001",
  name: "学习笔记",
  source_type: "text" as const,
  origin_uri: null,
  status: "review" as const,
  version: 1,
  lineage_id: "00000000-0000-4000-8000-000000000002",
  replaces_source_id: null,
  superseded_at: null,
  deleted_at: null,
  ingestion_config: {
    trainingType: "chunk" as const,
    indexPrefixTitle: true,
    customPdfParse: false,
    chunkSettingMode: "auto" as const,
    chunkSplitMode: "paragraph" as const,
    chunkSize: 1000,
    indexSize: 256,
    chunkSplitter: "",
    qaPrompt: "",
  },
  error_message: null,
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-04T00:00:00Z",
};

const capabilities: SourceIngestionCapabilities = {
  accepted_extensions: [".pdf", ".docx", ".pptx", ".xlsx", ".png"],
  max_upload_bytes: 20_000_000,
  settings: [
    { key: "customPdfParse", supported: true, disabled_reason: null },
  ],
  workspace_models: [],
  read_only_demo: false,
};

describe("SourceWizard", () => {
  it.each([{ items: [] }, { items: [{ position: 1, q: "  ", a: "\n", q_truncated: false, a_truncated: false }] }])("refreshes an empty preview without uploading again and recovers from read errors: %j", async ({ items }) => {
    const user = userEvent.setup();
    const actual = { authority: "actual", source_id: source.id, source_name: source.name, items, limit: 30 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(actual), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "external_service_error" } }), { status: 502 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...actual, items: [{ position: 1, q: "资料内容", a: "", q_truncated: false, a_truncated: false }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...source, status: "ready" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open existingSource={source} intent="review" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "接受并用于问答" })).toBeDisabled();
    expect(screen.getByText(/可能仍在处理/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "刷新处理结果" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前无法完成");
    await user.click(screen.getByRole("button", { name: "返回重试" }));
    expect(await screen.findByText("资料内容")).toBeVisible();
    expect(screen.getByRole("button", { name: "接受并用于问答" })).toBeEnabled();
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual(Array(3).fill(`/api/workspaces/${source.workspace_id}/sources/${source.id}/processed-preview`));
    await user.click(screen.getByRole("button", { name: "接受并用于问答" }));
    expect(await screen.findByText("资料已准备好")).toBeVisible();
  });

  it("keeps the simple settings path primary and explains advanced fields inline", async () => {
    const user = userEvent.setup();
    render(
      <SourceWizard
        workspaceId="00000000-0000-4000-8000-000000000001"
        capabilities={capabilities}
        open
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "粘贴文本" }));
    expect(screen.getByText("推荐设置")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "高级设置" }));
    expect(screen.getByLabelText("片段长度")).toBeVisible();
    expect(screen.getByText(/影响每个片段保留多少上下文/)).toBeVisible();
    expect(screen.getAllByText(/推荐/).length).toBeGreaterThan(1);
    expect(screen.getByLabelText("问答提取要求")).toBeVisible();
    expect(screen.getByLabelText("保存方式")).toBeVisible();
    expect(screen.getByLabelText("分块规则")).toBeVisible();
    expect(screen.getByLabelText("分段方式")).toBeVisible();
    expect(screen.getByLabelText("自定义分隔符")).toBeVisible();
    expect(screen.getByLabelText("将标题加入索引")).toBeVisible();
    expect(screen.getByLabelText("索引内容长度")).toBeVisible();
  });

  it("moves focus inside and closes with Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open onClose={onClose} onChanged={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "关闭资料向导" })).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not offer a provider-unverified control", async () => {
    const user = userEvent.setup();
    render(
      <SourceWizard
        workspaceId="00000000-0000-4000-8000-000000000001"
        capabilities={{
          ...capabilities,
          settings: [
            {
              key: "customPdfParse",
              supported: false,
              disabled_reason: "deployment_not_verified",
            },
          ],
        }}
        open
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "粘贴文本" }));
    await user.click(screen.getByRole("button", { name: "高级设置" }));
    expect(screen.getByLabelText("增强 PDF 解析")).toBeDisabled();
    expect(screen.getByText("当前部署尚未验证此能力")).toBeVisible();
  });

  it("does not call an API when a dropped file only opens the wizard", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SourceWizard
        workspaceId="00000000-0000-4000-8000-000000000001"
        capabilities={capabilities}
        open
        initialFile={new File(["notes"], "notes.pdf", { type: "application/pdf" })}
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(screen.getByText("notes.pdf")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("validates a dropped file before exposing settings or calling an API", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open initialFile={new File(["x"], "notes.exe")} onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByText(/当前支持/)).toBeVisible();
    expect(screen.queryByText("推荐设置")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps reprocessing inert until replacement input exists", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open existingSource={source} intent="reprocess" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByText("重新选择原资料后处理新版本")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("distinguishes estimated and actual results and accepts only after review", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/source-previews/text")) return new Response(JSON.stringify({ authority: "estimated", source_name: "学习笔记", character_count: 8, items: [{ position: 1, text: "检索会定位资料", character_count: 7, truncated: false, locator: null }], warnings: [] }), { status: 200 });
      if (url.endsWith("/sources/text")) return new Response(JSON.stringify({ source, processed_preview: { authority: "actual", source_id: source.id, source_name: source.name, items: [{ position: 1, q: "什么是检索？", a: "定位相关资料。", q_truncated: false, a_truncated: false }], limit: 30 } }), { status: 201 });
      if (url.endsWith("/accept")) return new Response(JSON.stringify({ ...source, status: "ready" }), { status: 200 });
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open onClose={vi.fn()} onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "粘贴文本" }));
    await user.type(screen.getByLabelText("资料内容"), "检索会定位资料");
    await user.click(screen.getByRole("button", { name: "查看预计片段" }));
    expect(await screen.findByText("本地估算")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "确认处理" }));
    expect(await screen.findByText("实际处理结果")).toBeVisible();
    expect(screen.getByText("待复核")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "接受并用于问答" }));
    expect(await screen.findByText("资料已准备好")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not offer acceptance for an already-ready source", async () => {
    const ready = { ...source, status: "ready" as const };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ authority: "actual", source_id: ready.id, source_name: ready.name, items: [{ position: 1, q: "问题", a: "答案", q_truncated: false, a_truncated: false }], limit: 30 }), { status: 200 })));
    render(<SourceWizard workspaceId={ready.workspace_id} capabilities={capabilities} open existingSource={ready} intent="review" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByText("已就绪")).toBeVisible();
    expect(screen.queryByRole("button", { name: "接受并用于问答" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭" })).toBeVisible();
  });

  it("returns an accept failure to the existing actual review", async () => {
    const user = userEvent.setup();
    const actual = { authority: "actual", source_id: source.id, source_name: source.name, items: [{ position: 1, q: "问题", a: "答案", q_truncated: false, a_truncated: false }], limit: 30 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(actual), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "external_service_error" } }), { status: 502 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open existingSource={source} intent="review" onClose={vi.fn()} onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "接受并用于问答" }));
    expect(await screen.findByText(/当前无法完成/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "返回重试" }));
    expect(screen.getByText("实际处理结果")).toBeVisible();
    expect(screen.getByRole("button", { name: "接受并用于问答" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries an unavailable actual preview instead of opening a blank review", async () => {
    const user = userEvent.setup();
    const actual = { authority: "actual", source_id: source.id, source_name: source.name, items: [{ position: 1, q: "问题", a: "答案", q_truncated: false, a_truncated: false }], limit: 30 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "processed_preview_unavailable" } }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(actual), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open existingSource={source} intent="review" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByText(/实际处理结果暂时不可用/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "返回重试" }));
    expect(await screen.findByText("实际处理结果")).toBeVisible();
    expect(screen.getByText("待复核")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reprocesses the just-reviewed source when settings are adjusted", async () => {
    const user = userEvent.setup();
    const estimated = { authority: "estimated", source_name: "学习笔记", character_count: 8, items: [{ position: 1, text: "检索会定位资料", character_count: 7, truncated: false, locator: null }], warnings: [] };
    const actual = { authority: "actual", source_id: source.id, source_name: source.name, items: [{ position: 1, q: "问题", a: "答案", q_truncated: false, a_truncated: false }], limit: 30 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("source-previews")) return new Response(JSON.stringify(estimated), { status: 200 });
      if (url.endsWith(`/${source.id}`)) return new Response(null, { status: 204 });
      if (url.endsWith("/text")) return new Response(JSON.stringify({ source, processed_preview: actual }), { status: 201 });
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open onClose={vi.fn()} onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "粘贴文本" }));
    await user.type(screen.getByLabelText("资料内容"), "检索会定位资料");
    await user.click(screen.getByRole("button", { name: "查看预计片段" }));
    await user.click(await screen.findByRole("button", { name: "确认处理" }));
    await user.click(await screen.findByRole("button", { name: "调整设置并重新处理" }));
    await user.click(screen.getByRole("button", { name: "粘贴文本" }));
    await user.click(screen.getByRole("button", { name: "查看预计片段" }));
    await user.click(await screen.findByRole("button", { name: "确认处理" }));
    await screen.findByText("实际处理结果");
    const calls = fetchMock.mock.calls.map(([input, init]) => [String(input), init?.method]);
    expect(calls).toContainEqual([`/api/workspaces/${source.workspace_id}/sources/${source.id}`, "DELETE"]);
    expect(calls.filter(([url]) => url === `/api/workspaces/${source.workspace_id}/sources/text`)).toHaveLength(2);
    expect(calls.some(([url]) => String(url).includes("/reprocess/"))).toBe(false);
  });

  it("guards pending-review cleanup against double activation", async () => {
    let finishDelete: ((response: Response) => void) | undefined;
    const actual = { authority: "actual", source_id: source.id, source_name: source.name, items: [{ position: 1, q: "问题", a: "答案", q_truncated: false, a_truncated: false }], limit: 30 };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(actual), { status: 200 }))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishDelete = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SourceWizard workspaceId={source.workspace_id} capabilities={capabilities} open existingSource={source} intent="review" onClose={vi.fn()} onChanged={vi.fn()} />);
    const adjust = await screen.findByRole("button", { name: "调整设置并重新处理" });
    adjust.click();
    adjust.click();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    finishDelete?.(new Response(null, { status: 204 }));
    expect(await screen.findByText("重新选择原资料后处理新版本")).toBeVisible();
  });
});
