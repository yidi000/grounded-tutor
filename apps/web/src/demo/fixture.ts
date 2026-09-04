import type {
  CapabilityItem,
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
  topic: Readonly<{
    label: "示例主题";
    title: "RAG 基础";
  }>;
  localInstructionsUrl: string;
  capabilities: ReadonlyCapabilities;
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

export const demoFixture: DemoFixture = Object.freeze({
  topic: Object.freeze({
    label: "示例主题",
    title: "RAG 基础",
  }),
  localInstructionsUrl: "/README.md#fake-adapter-quick-start",
  capabilities,
});
