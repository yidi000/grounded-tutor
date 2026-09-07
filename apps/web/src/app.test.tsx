import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./api/client";
import {
  ChunkSettingsSchema,
  ChatRequestSchema,
  ChatResponseSchema,
  SourceIngestionCapabilitiesSchema,
  SourceIngestionResponseSchema,
  SourceLocatorSchema,
  WorkspaceCreateSchema,
  WorkspaceResponseSchema,
} from "./api/types";
import type { ChatRequestInput } from "./api/types";
import { App } from "./app";
import { parseAppMode } from "./config";
import { demoFixture } from "./demo/fixture";

describe("Foundation API contracts", () => {
  it("parses every backend SourceLocator variant by kind", () => {
    const locators = [
      { kind: "chunk", label: "片段 18" },
      { kind: "pdf", page: 12, section: "2.3" },
      { kind: "docx", heading_path: ["分块"], paragraph: 3 },
      { kind: "pptx", slide: 6, title: "召回" },
      { kind: "xlsx", sheet: "实验", cell_range: "A1:C8" },
      { kind: "image", filename: "diagram.png", region: null },
    ];

    expect(locators.map((locator) => SourceLocatorSchema.parse(locator))).toEqual(
      locators,
    );
    expect(() =>
      SourceLocatorSchema.parse({ kind: "pdf", page: 0, section: null }),
    ).toThrow(z.ZodError);
  });

  it("parses current capability and Workspace shapes", () => {
    expect(
      SourceIngestionCapabilitiesSchema.parse({
        accepted_extensions: [".pdf", ".txt"],
        max_upload_bytes: 10_000,
        settings: [
          {
            key: "customPdfParse",
            supported: false,
            disabled_reason: "deployment_not_verified",
          },
        ],
        workspace_models: [
          {
            key: "vector_model",
            supported: true,
            disabled_reason: null,
          },
        ],
        read_only_demo: false,
      }).read_only_demo,
    ).toBe(false);

    expect(
      WorkspaceCreateSchema.parse({ title: "  统计学复习  ", agent_model: " " }),
    ).toEqual({ title: "统计学复习", agent_model: null });

    expect(
      WorkspaceCreateSchema.parse({
        title: "统计学复习",
        server_added_field: "ignored",
      }),
    ).toEqual({ title: "统计学复习" });

    expect(
      WorkspaceResponseSchema.parse({
        id: "00000000-0000-4000-8000-000000000001",
        title: "统计学复习",
        source_count: 2,
        ready_source_count: 1,
        model_choices: {
          vector_model: null,
          agent_model: null,
          vlm_model: null,
        },
        created_at: "2026-09-04T00:00:00Z",
        updated_at: "2026-09-04T00:00:00Z",
      }).ready_source_count,
    ).toBe(1);
  });

  it("accepts offset and SQLite-naive backend datetimes", () => {
    const workspace = {
      id: "00000000-0000-4000-8000-000000000001",
      title: "统计学复习",
      source_count: 0,
      ready_source_count: 0,
      model_choices: {
        vector_model: null,
        agent_model: null,
        vlm_model: null,
      },
      created_at: "2026-09-04T08:00:00+08:00",
      updated_at: "2026-09-04T00:00:00.000000",
    };

    expect(WorkspaceResponseSchema.parse(workspace)).toMatchObject({
      created_at: workspace.created_at,
      updated_at: workspace.updated_at,
    });
  });

  it("applies backend ChunkSettings defaults", () => {
    expect(ChunkSettingsSchema.parse({})).toEqual({
      trainingType: "chunk",
      indexPrefixTitle: true,
      customPdfParse: false,
      chunkSettingMode: "auto",
      chunkSplitMode: "paragraph",
      chunkSize: 1000,
      indexSize: 256,
      chunkSplitter: "",
      qaPrompt: "",
    });
  });

  it("bounds chunkSize only in chunk mode", () => {
    expect(() =>
      ChunkSettingsSchema.parse({ chunkSize: 99, indexSize: 32 }),
    ).toThrow(z.ZodError);
    expect(() =>
      ChunkSettingsSchema.parse({ chunkSize: 3001, indexSize: 32 }),
    ).toThrow(z.ZodError);
    expect(
      ChunkSettingsSchema.parse({
        trainingType: "qa",
        chunkSize: 50,
        indexSize: 32,
      }).chunkSize,
    ).toBe(50);
  });

  it("enforces backend indexSize bounds", () => {
    expect(() => ChunkSettingsSchema.parse({ indexSize: 31 })).toThrow(
      z.ZodError,
    );
    expect(() =>
      ChunkSettingsSchema.parse({ chunkSize: 100, indexSize: 101 }),
    ).toThrow(z.ZodError);
  });

  it("enforces backend splitter and prompt limits", () => {
    expect(() =>
      ChunkSettingsSchema.parse({
        chunkSettingMode: "custom",
        chunkSplitMode: "char",
        chunkSplitter: "",
      }),
    ).toThrow(z.ZodError);
    expect(() =>
      ChunkSettingsSchema.parse({ chunkSplitter: "x".repeat(21) }),
    ).toThrow(z.ZodError);
    expect(() =>
      ChunkSettingsSchema.parse({ qaPrompt: "x".repeat(4_001) }),
    ).toThrow(z.ZodError);
  });

  it("parses the current Source summary and actual processed preview", () => {
    const id = "00000000-0000-4000-8000-000000000002";
    const source = {
      id,
      workspace_id: "00000000-0000-4000-8000-000000000001",
      name: "notes.pdf",
      source_type: "file",
      origin_uri: null,
      status: "review",
      version: 1,
      lineage_id: id,
      replaces_source_id: null,
      superseded_at: null,
      deleted_at: null,
      ingestion_config: {
        trainingType: "chunk",
        indexPrefixTitle: true,
        customPdfParse: false,
        chunkSettingMode: "auto",
        chunkSplitMode: "paragraph",
        chunkSize: 1000,
        indexSize: 256,
        chunkSplitter: "",
        qaPrompt: "",
      },
      error_message: null,
      created_at: "2026-09-04T00:00:00Z",
      updated_at: "2026-09-04T00:00:00Z",
    };

    expect(
      SourceIngestionResponseSchema.parse({
        source,
        processed_preview: {
          authority: "actual",
          source_id: id,
          source_name: "notes.pdf",
          items: [
            {
              position: 1,
              q: "什么是检索？",
              a: "先定位相关资料。",
              q_truncated: false,
              a_truncated: false,
            },
          ],
          limit: 30,
        },
      }).source.status,
    ).toBe("review");
  });

  it("parses grounded Chat blocks, citations, and suggested actions", () => {
    const newConversation: ChatRequestInput = {
      message: "  什么是分块？ ",
      idempotency_key: " request-1 ",
    };
    expect(ChatRequestSchema.parse(newConversation)).toEqual({
      conversation_id: null,
      message: "什么是分块？",
      idempotency_key: "request-1",
    });

    expect(
      ChatRequestSchema.parse({
        conversation_id: null,
        message: "  什么是分块？ ",
        idempotency_key: " request-1 ",
      }),
    ).toEqual({
      conversation_id: null,
      message: "什么是分块？",
      idempotency_key: "request-1",
    });

    const response = ChatResponseSchema.parse({
      conversation_id: "00000000-0000-4000-8000-000000000010",
      message_id: "00000000-0000-4000-8000-000000000011",
      status: "ok",
      answer_blocks: [
        {
          id: "block-1",
          kind: "answer",
          text: "分块让检索定位到更小的资料范围。",
          citation_ids: ["citation-1"],
        },
      ],
      citations: [
        {
          id: "citation-1",
          source_id: "00000000-0000-4000-8000-000000000002",
          source_name: "notes.pdf",
          source_version: 1,
          chunk_id: "chunk-18",
          excerpt: "先把长资料分成较小片段。",
          context_before: null,
          context_after: null,
          locator: { kind: "pdf", page: 12, section: "分块边界" },
        },
      ],
      suggested_actions: [
        { type: "add_material" },
        { type: "suggest_new_workspace", proposed_title: "向量检索" },
        {
          type: "resume_activity",
          label: "继续第 2 题",
          checkpoint: "question-2",
        },
      ],
    });

    expect(response.citations[0].locator.kind).toBe("pdf");
    expect(() =>
      ChatResponseSchema.parse({
        ...response,
        answer_blocks: [{ ...response.answer_blocks[0], citation_ids: [] }],
      }),
    ).toThrow(z.ZodError);
  });
});

describe("apiFetch", () => {
  it("parses successful JSON with the supplied schema", async () => {
    const schema = z.object({ ready: z.boolean() });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ready: true }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ready: "yes" }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch(schema, "/api/ready")).resolves.toEqual({
      ready: true,
    });
    await expect(apiFetch(schema, "/api/ready")).rejects.toBeInstanceOf(
      z.ZodError,
    );
  });

  it("throws only a stable, redacted error for failed responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "file_too_large",
              provider_payload: "secret-token",
            },
          }),
          { status: 413 },
        ),
      ),
    );

    let error: unknown;
    try {
      await apiFetch(z.object({}), "/api/upload");
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) throw error;
    expect(error.status).toBe(413);
    expect(error.code).toBe("file_too_large");
    expect(error.message).toBe("file_too_large");
    expect(error.message).not.toContain("secret-token");
  });

  it("uses a safe public fallback when a failed response is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("provider-secret-and-details", { status: 502 }),
      ),
    );

    let error: unknown;
    try {
      await apiFetch(z.object({}), "/api/chat");
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) throw error;
    expect(error.status).toBe(502);
    expect(error.code).toBe("external_service_error");
    expect(error.message).toBe("external_service_error");
    expect(error.message).not.toContain("provider-secret-and-details");
  });

  it("sets JSON content type without touching multipart boundaries", async () => {
    const requests: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input, init) => {
        requests.push(init ?? {});
        return new Response("{}", { status: 200 });
      }),
    );

    await apiFetch(z.object({}), "/api/json", {
      method: "POST",
      body: "{}",
    });
    await apiFetch(z.object({}), "/api/file", {
      method: "POST",
      body: new FormData(),
    });

    expect(new Headers(requests[0].headers).get("Content-Type")).toBe(
      "application/json",
    );
    expect(new Headers(requests[1].headers).has("Content-Type")).toBe(false);
  });
});

describe("configuration", () => {
  it("accepts only the two public application modes", () => {
    expect(parseAppMode("local")).toBe("local");
    expect(parseAppMode("demo_read_only")).toBe("demo_read_only");
    expect(() => parseAppMode("preview")).toThrow(
      "VITE_APP_MODE must be local or demo_read_only",
    );
  });
});

describe("App", () => {
  it("loads local ingestion capabilities before exposing supported controls", async () => {
    let finishRequest: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finishRequest = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App mode="local" />);

    expect(screen.getByText("正在读取资料能力")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "上传你的资料" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "创建学习主题" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/capabilities/source-ingestion",
      { signal: expect.any(AbortSignal) },
    );

    finishRequest?.(
      new Response(
        JSON.stringify({
          accepted_extensions: [".pdf"],
          max_upload_bytes: 10_000,
          settings: [],
          workspace_models: [],
          read_only_demo: false,
        }),
        { status: 200 },
      ),
    );
    expect(await screen.findByText("资料能力已读取")).toBeVisible();
  });

  it("reports a local capability failure without exposing unsupported controls", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("private upstream details", { status: 503 }),
      ),
    );

    render(<App mode="local" />);

    expect(
      await screen.findByText("暂时无法读取资料能力"),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "上传你的资料" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("private upstream details"),
    ).not.toBeInTheDocument();
  });

  it("renders the local three-column Evidence Notebook", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    render(<App mode="local" />);

    expect(screen.getByRole("banner")).toHaveTextContent("Grounded Tutor");
    expect(screen.getByRole("navigation", { name: "学习主题" })).toBeVisible();
    expect(screen.getByRole("main")).toBeVisible();
    expect(screen.getByRole("complementary", { name: "上下文" })).toBeVisible();
    expect(screen.getAllByLabelText("向资料提问")).toHaveLength(1);
  });

  it("renders one immutable sample topic in demo mode", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<App mode="demo_read_only" />);

    expect(screen.getByText("示例主题")).toBeVisible();
    expect(screen.getByText("RAG 基础")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "创建学习主题" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "上传你的资料" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "在本地使用我的资料" }),
    ).toHaveAttribute("href", "/local-setup.html");
    expect(screen.getByLabelText("向资料提问")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "重命名学习主题" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(demoFixture.capabilities.read_only_demo).toBe(true);
    expect(Object.isFrozen(demoFixture)).toBe(true);
    expect(Object.isFrozen(demoFixture.capabilities)).toBe(true);
  });

  it("sends a local ASK and opens its structured citation", async () => {
    const user = userEvent.setup();
    const workspaceId = "00000000-0000-4000-8000-000000000001";
    const sourceId = "00000000-0000-4000-8000-000000000002";
    const newWorkspaceId = "00000000-0000-4000-8000-000000000003";
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/chat/history")) return Response.json({ exchanges: [] });
      requests.push({ url, init });
      if (url === "/api/capabilities/source-ingestion") return Response.json({ accepted_extensions: [".txt"], max_upload_bytes: 10_000, settings: [], workspace_models: [], read_only_demo: false });
      if (url === "/api/workspaces" && init?.method === "POST") return Response.json({ id: newWorkspaceId, title: "Probability", source_count: 0, ready_source_count: 0, model_choices: { vector_model: null, agent_model: null, vlm_model: null }, created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:00Z" });
      if (url === "/api/workspaces") return Response.json([{ id: workspaceId, title: "Intro Statistics", source_count: 1, ready_source_count: 1, model_choices: { vector_model: null, agent_model: null, vlm_model: null }, created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:00Z" }]);
      if (url === `/api/workspaces/${workspaceId}/sources`) return Response.json([]);
      if (url === `/api/workspaces/${newWorkspaceId}/sources`) return Response.json([]);
      if (url === `/api/workspaces/${workspaceId}/chat`) return Response.json({ conversation_id: "00000000-0000-4000-8000-000000000010", message_id: "00000000-0000-4000-8000-000000000011", status: "ok", answer_blocks: [{ id: "block-1", kind: "answer", text: "The mean is the average.", citation_ids: ["citation-1"] }], citations: [{ id: "citation-1", source_id: sourceId, source_name: "Week 1 notes", source_version: 1, chunk_id: "chunk-1", excerpt: "Mean is an average.", context_before: null, context_after: null, locator: { kind: "chunk", label: "匹配片段 1" } }], suggested_actions: [] });
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App mode="local" />);
    await screen.findByRole("heading", { name: "Intro Statistics" });
    const input = screen.getByLabelText("向资料提问");
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "What is a mean?");
    await user.click(screen.getByRole("button", { name: "发送" }));

    const anchor = await screen.findByRole("button", { name: "引用 1：Week 1 notes" });
    await user.click(anchor);
    expect(screen.getByRole("complementary", { name: "上下文" })).toHaveTextContent("Mean is an average.");
    const chatRequest = requests.find(({ url }) => url.endsWith("/chat"));
    expect(JSON.parse(String(chatRequest?.init?.body))).toMatchObject({ conversation_id: null, message: "What is a mean?" });

    await user.click(screen.getByRole("button", { name: "创建学习主题" }));
    await user.type(screen.getByLabelText("主题名称"), "Probability");
    await user.click(screen.getByRole("button", { name: "创建主题" }));
    const createdDialog = await screen.findByRole("dialog", { name: "主题已创建" });
    await user.click(within(createdDialog).getByRole("button", { name: "进入主题" }));

    expect(screen.queryByText("The mean is the average.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "引用 1：Week 1 notes" })).not.toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "上下文" })).not.toHaveTextContent("Mean is an average.");
  });

  it("discards an ASK response after switching Workspace", async () => {
    const user = userEvent.setup();
    const firstId = "00000000-0000-4000-8000-000000000001";
    const secondId = "00000000-0000-4000-8000-000000000002";
    let resolveFirst: ((response: Response) => void) | undefined;
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/chat/history")) return Response.json({ exchanges: [] });
      requests.push({ url, init });
      if (url === "/api/capabilities/source-ingestion") return Response.json({ accepted_extensions: [".txt"], max_upload_bytes: 10_000, settings: [], workspace_models: [], read_only_demo: false });
      if (url === "/api/workspaces") return Response.json([
        { id: firstId, title: "Workspace A", source_count: 1, ready_source_count: 1, model_choices: { vector_model: null, agent_model: null, vlm_model: null }, created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:00Z" },
        { id: secondId, title: "Workspace B", source_count: 1, ready_source_count: 1, model_choices: { vector_model: null, agent_model: null, vlm_model: null }, created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:00Z" },
      ]);
      if (url.endsWith("/sources")) return Response.json([]);
      if (url === `/api/workspaces/${firstId}/chat`) return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      if (url === `/api/workspaces/${secondId}/chat`) return Response.json({ conversation_id: "00000000-0000-4000-8000-000000000020", message_id: "00000000-0000-4000-8000-000000000021", status: "ok", answer_blocks: [{ id: "block-b", kind: "answer", text: "Answer from B.", citation_ids: ["citation-b"] }], citations: [{ id: "citation-b", source_id: secondId, source_name: "Notes B", source_version: 1, chunk_id: "chunk-b", excerpt: "Evidence B", context_before: null, context_after: null, locator: { kind: "chunk", label: "片段 B" } }], suggested_actions: [] });
      throw new Error(`Unexpected request ${url}`);
    }));

    render(<App mode="local" />);
    await screen.findByRole("heading", { name: "Workspace A" });
    const input = screen.getByLabelText("向资料提问");
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Question for A");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(requests.filter(({ url }) => url === `/api/workspaces/${firstId}/chat`)).toHaveLength(1);
    const workspaceB = within(screen.getByRole("navigation", { name: "学习主题" }))
      .getByText("Workspace B")
      .closest("button");
    if (!workspaceB) throw new Error("Workspace B selector is missing");
    await user.click(workspaceB);
    expect(screen.getByRole("heading", { name: "Workspace B" })).toBeVisible();
    const inputB = screen.getByLabelText("向资料提问");
    expect(inputB).toHaveValue("");
    await waitFor(() => expect(inputB).toBeEnabled());
    await user.type(inputB, "Question for B");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("Answer from B.")).toBeVisible();
    const secondRequest = requests.find(({ url }) => url === `/api/workspaces/${secondId}/chat`);
    expect(JSON.parse(String(secondRequest?.init?.body))).toMatchObject({ conversation_id: null, message: "Question for B" });

    await user.type(inputB, "B draft survives");
    await act(async () => {
      resolveFirst?.(Response.json({ conversation_id: "00000000-0000-4000-8000-000000000010", message_id: "00000000-0000-4000-8000-000000000011", status: "ok", answer_blocks: [{ id: "block-a", kind: "answer", text: "Late answer from A.", citation_ids: ["citation-a"] }], citations: [{ id: "citation-a", source_id: firstId, source_name: "Notes A", source_version: 1, chunk_id: "chunk-a", excerpt: "Evidence A", context_before: null, context_after: null, locator: { kind: "chunk", label: "片段 A" } }], suggested_actions: [] }));
      await Promise.resolve();
    });

    expect(screen.queryByText("Late answer from A.")).not.toBeInTheDocument();
    expect(inputB).toHaveValue("B draft survives");
  });

  it("renders a fixed cited answer in demo without network writes", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<App mode="demo_read_only" />);
    await user.click(screen.getByRole("button", { name: /引用 1/ }));

    expect(screen.getByRole("complementary", { name: "上下文" })).toHaveTextContent("RAG");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
