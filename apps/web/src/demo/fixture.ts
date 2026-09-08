import type {
  CapabilityItem,
  ChatResponse,
  SourceIngestionCapabilities,
} from "../api/types";

type ReadonlyCapabilities = Readonly<
  Omit<
    SourceIngestionCapabilities,
    "accepted_extensions" | "settings" | "workspace_models"
  >
> &
  Readonly<{
    accepted_extensions: readonly string[];
    settings: readonly Readonly<CapabilityItem>[];
    workspace_models: readonly Readonly<CapabilityItem>[];
  }>;

export type DemoFixture = Readonly<{
  version: "rag-demo-v1";
  provenance: Readonly<{ license: "CC0-1.0"; origin: string }>;
  topic: Readonly<{
    label: "示例主题";
    title: "RAG 基础";
  }>;
  localInstructionsUrl: string;
  capabilities: ReadonlyCapabilities;
  exchange: Readonly<{ question: string; response: ChatResponse }>;
}>;

const demoDisabled = (key: string): Readonly<CapabilityItem> =>
  Object.freeze({
    key,
    supported: false,
    disabled_reason: "demo_read_only",
  });

const capabilities: ReadonlyCapabilities = Object.freeze({
  accepted_extensions: Object.freeze([
    ".csv",
    ".docx",
    ".html",
    ".md",
    ".pdf",
    ".pptx",
    ".txt",
    ".xlsx",
  ]),
  max_upload_bytes: 20_000_000,
  settings: Object.freeze([
    demoDisabled("customPdfParse"),
    demoDisabled("imageFiles"),
  ]),
  workspace_models: Object.freeze([
    demoDisabled("vector_model"),
    demoDisabled("agent_model"),
    demoDisabled("vlm_model"),
  ]),
  read_only_demo: true,
});

const demoResponse: ChatResponse = {
  conversation_id: "00000000-0000-4000-8000-000000000010",
  message_id: "00000000-0000-4000-8000-000000000011",
  status: "ok",
  answer_blocks: [
    {
      id: "demo-block-1",
      kind: "answer",
      text: "RAG 先从资料中检索相关片段，再让模型依据这些片段组织回答。显示引用让学习者能核对结论是否真的受到资料支持。",
      citation_ids: ["demo-citation-1"],
    },
  ],
  citations: [
    {
      id: "demo-citation-1",
      source_id: "00000000-0000-4000-8000-000000000002",
      source_name: "RAG 学习笔记",
      source_version: 1,
      chunk_id: "demo-chunk-1",
      excerpt: "检索增强生成会先取得与问题有关的资料片段，再以这些片段作为回答依据。引用使读者能够回到资料核对结论。",
      context_before: null,
      context_after: "资料没有覆盖的问题，应明确说明依据不足。",
      locator: { kind: "chunk", label: "匹配片段 1" },
    },
  ],
  suggested_actions: [],
};

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

export const demoFixture: DemoFixture = deepFreeze({
  version: "rag-demo-v1",
  provenance: { license: "CC0-1.0", origin: "Original synthetic Chinese RAG example for Grounded Tutor" },
  topic: Object.freeze({
    label: "示例主题",
    title: "RAG 基础",
  }),
  localInstructionsUrl: `${import.meta.env.BASE_URL}local-setup.html`,
  capabilities,
  exchange: Object.freeze({
    question: "为什么 RAG 的回答还需要显示资料依据？",
    response: demoResponse,
  }),
});
