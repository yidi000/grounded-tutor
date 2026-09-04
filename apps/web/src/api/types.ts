import { z } from "zod";

export const PublicErrorCodeSchema = z.enum([
  "demo_read_only",
  "empty_processed_source",
  "empty_source",
  "external_service_error",
  "file_too_large",
  "idempotency_key_reused",
  "invalid_chunk_settings",
  "invalid_source_transition",
  "persistence_error",
  "processed_preview_unavailable",
  "request_body_too_large",
  "source_not_found",
  "source_too_large",
  "source_work_limit_exceeded",
  "text_too_large",
  "unreadable_file",
  "unsafe_archive",
  "unsupported_file_type",
  "unsupported_workspace_model",
  "validation_error",
  "workspace_ingestion_busy",
  "workspace_not_found",
]);
export type PublicErrorCode = z.infer<typeof PublicErrorCodeSchema>;

export const ApiErrorResponseSchema = z.object({
  detail: z.object({ code: PublicErrorCodeSchema }),
});

const ChunkLocatorSchema = z
  .object({
    kind: z.literal("chunk"),
    label: z.string().trim().min(1),
  })
  .strict();

const PdfLocatorSchema = z
  .object({
    kind: z.literal("pdf"),
    page: z.number().int().min(1),
    section: z.string().nullable(),
  })
  .strict();

const DocxLocatorSchema = z
  .object({
    kind: z.literal("docx"),
    heading_path: z.array(z.string()),
    paragraph: z.number().int().min(1).nullable(),
  })
  .strict();

const PptxLocatorSchema = z
  .object({
    kind: z.literal("pptx"),
    slide: z.number().int().min(1),
    title: z.string().nullable(),
  })
  .strict();

const XlsxLocatorSchema = z
  .object({
    kind: z.literal("xlsx"),
    sheet: z.string().trim().min(1),
    cell_range: z.string().nullable(),
  })
  .strict();

const ImageLocatorSchema = z
  .object({
    kind: z.literal("image"),
    filename: z.string().trim().min(1),
    region: z.string().nullable(),
  })
  .strict();

export const SourceLocatorSchema = z.discriminatedUnion("kind", [
  ChunkLocatorSchema,
  PdfLocatorSchema,
  DocxLocatorSchema,
  PptxLocatorSchema,
  XlsxLocatorSchema,
  ImageLocatorSchema,
]);
export type SourceLocator = z.infer<typeof SourceLocatorSchema>;

export const CapabilityItemSchema = z.object({
  key: z.string(),
  supported: z.boolean(),
  disabled_reason: z
    .enum(["deployment_not_verified", "demo_read_only"])
    .nullable(),
});
export type CapabilityItem = z.infer<typeof CapabilityItemSchema>;

export const SourceIngestionCapabilitiesSchema = z.object({
  accepted_extensions: z.array(z.string()),
  max_upload_bytes: z.number().int(),
  settings: z.array(CapabilityItemSchema),
  workspace_models: z.array(CapabilityItemSchema),
  read_only_demo: z.boolean(),
});
export type SourceIngestionCapabilities = z.infer<
  typeof SourceIngestionCapabilitiesSchema
>;

const optionalModelSchema = z
  .string()
  .nullable()
  .optional()
  .transform((value) => {
    if (typeof value !== "string") return value;
    return value.trim() || null;
  });

export const WorkspaceCreateSchema = z
  .object({
    title: z.string().trim().min(1).max(120),
    vector_model: optionalModelSchema,
    agent_model: optionalModelSchema,
    vlm_model: optionalModelSchema,
  });
export type WorkspaceCreate = z.infer<typeof WorkspaceCreateSchema>;

export const WorkspaceUpdateSchema = z
  .object({ title: z.string().trim().min(1).max(120) })
  .strict();
export type WorkspaceUpdate = z.infer<typeof WorkspaceUpdateSchema>;

export const WorkspaceModelChoicesSchema = z.object({
  vector_model: z.string().nullable(),
  agent_model: z.string().nullable(),
  vlm_model: z.string().nullable(),
});
export type WorkspaceModelChoices = z.infer<
  typeof WorkspaceModelChoicesSchema
>;

const uuidSchema = z.string().uuid();
const dateTimeSchema = z.iso.datetime({ offset: true, local: true });

export const WorkspaceResponseSchema = z.object({
  id: uuidSchema,
  title: z.string(),
  source_count: z.number().int(),
  ready_source_count: z.number().int(),
  model_choices: WorkspaceModelChoicesSchema,
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
});
export type WorkspaceResponse = z.infer<typeof WorkspaceResponseSchema>;
export type WorkspaceSummary = WorkspaceResponse;

export const SourceStatusSchema = z.enum([
  "uploading",
  "parsing",
  "indexing",
  "review",
  "ready",
  "failed",
]);
export type SourceStatus = z.infer<typeof SourceStatusSchema>;

export const SourceTypeSchema = z.enum(["file", "text", "webpage"]);
export type SourceType = z.infer<typeof SourceTypeSchema>;

export const ChunkSettingsSchema = z
  .object({
    trainingType: z.enum(["chunk", "qa"]).default("chunk"),
    indexPrefixTitle: z.boolean().default(true),
    customPdfParse: z.boolean().default(false),
    chunkSettingMode: z.enum(["auto", "custom"]).default("auto"),
    chunkSplitMode: z
      .enum(["paragraph", "size", "char"])
      .default("paragraph"),
    chunkSize: z.number().int().default(1_000),
    indexSize: z.number().int().default(256),
    chunkSplitter: z.string().max(20).default(""),
    qaPrompt: z.string().max(4_000).default(""),
  })
  .strict()
  .superRefine((settings, context) => {
    if (
      settings.trainingType === "chunk" &&
      (settings.chunkSize < 100 || settings.chunkSize > 3_000)
    ) {
      context.addIssue({
        code: "custom",
        path: ["chunkSize"],
        message: "chunkSize must be between 100 and 3000 in chunk mode",
      });
    }
    if (settings.indexSize < 32) {
      context.addIssue({
        code: "custom",
        path: ["indexSize"],
        message: "indexSize must be at least 32",
      });
    }
    if (settings.indexSize > settings.chunkSize) {
      context.addIssue({
        code: "custom",
        path: ["indexSize"],
        message: "indexSize must not exceed chunkSize",
      });
    }
    if (
      settings.chunkSettingMode === "custom" &&
      settings.chunkSplitMode === "char" &&
      !settings.chunkSplitter
    ) {
      context.addIssue({
        code: "custom",
        path: ["chunkSplitter"],
        message: "chunkSplitter is required for custom delimiter splitting",
      });
    }
  });
export type ChunkSettings = z.infer<typeof ChunkSettingsSchema>;

export const SourceResponseSchema = z.object({
  id: uuidSchema,
  workspace_id: uuidSchema,
  name: z.string(),
  source_type: SourceTypeSchema,
  origin_uri: z.string().nullable(),
  status: SourceStatusSchema,
  version: z.number().int(),
  lineage_id: uuidSchema,
  replaces_source_id: uuidSchema.nullable(),
  superseded_at: dateTimeSchema.nullable(),
  deleted_at: dateTimeSchema.nullable(),
  ingestion_config: ChunkSettingsSchema,
  error_message: z.string().nullable(),
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
});
export type SourceResponse = z.infer<typeof SourceResponseSchema>;
export type SourceSummary = SourceResponse;

export const PreviewItemSchema = z.object({
  position: z.number().int(),
  text: z.string(),
  character_count: z.number().int(),
  truncated: z.boolean(),
  locator: SourceLocatorSchema.nullable(),
});

export const PreviewResponseSchema = z.object({
  authority: z.literal("estimated"),
  source_name: z.string(),
  character_count: z.number().int(),
  items: z.array(PreviewItemSchema),
  warnings: z.array(z.object({ code: z.string() })),
});
export type PreviewResponse = z.infer<typeof PreviewResponseSchema>;

export const ProcessedPreviewItemResponseSchema = z.object({
  position: z.number().int(),
  q: z.string(),
  a: z.string(),
  q_truncated: z.boolean(),
  a_truncated: z.boolean(),
});
export type ProcessedPreviewItemResponse = z.infer<
  typeof ProcessedPreviewItemResponseSchema
>;

export const ProcessedPreviewResponseSchema = z.object({
  authority: z.literal("actual"),
  source_id: uuidSchema,
  source_name: z.string(),
  items: z.array(ProcessedPreviewItemResponseSchema),
  limit: z.number().int(),
});
export type ProcessedPreviewResponse = z.infer<
  typeof ProcessedPreviewResponseSchema
>;

export const SourceIngestionResponseSchema = z.object({
  source: SourceResponseSchema,
  processed_preview: ProcessedPreviewResponseSchema,
});
export type SourceIngestionResponse = z.infer<
  typeof SourceIngestionResponseSchema
>;

const citationIdsSchema = z
  .array(z.string().trim().min(1))
  .min(1)
  .refine((ids) => new Set(ids).size === ids.length, {
    message: "citation ids must be unique",
  });

export const GroundedContentBlockSchema = z
  .object({
    id: z.string().trim().min(1),
    kind: z.enum(["answer", "definition", "explanation", "example"]),
    text: z.string().trim().min(1),
    citation_ids: citationIdsSchema,
  })
  .strict();
export type GroundedContentBlock = z.infer<
  typeof GroundedContentBlockSchema
>;

export const CitationSchema = z
  .object({
    id: z.string().trim().min(1),
    source_id: uuidSchema,
    source_name: z.string().trim().min(1),
    source_version: z.number().int().min(1),
    chunk_id: z.string().trim().min(1),
    excerpt: z.string().trim().min(1),
    context_before: z.string().nullable(),
    context_after: z.string().nullable(),
    locator: SourceLocatorSchema,
  })
  .strict();
export type Citation = z.infer<typeof CitationSchema>;

export const SuggestedActionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("add_material") }).strict(),
  z.object({ type: z.literal("rephrase") }).strict(),
  z.object({ type: z.literal("start_diagnostic") }).strict(),
  z
    .object({
      type: z.literal("suggest_new_workspace"),
      proposed_title: z.string(),
    })
    .strict(),
  z
    .object({
      type: z.literal("resume_activity"),
      label: z.string(),
      checkpoint: z.string(),
    })
    .strict(),
]);
export type SuggestedAction = z.infer<typeof SuggestedActionSchema>;

export const ChatRequestSchema = z
  .object({
    conversation_id: uuidSchema.nullable().default(null),
    message: z.string().trim().min(1).max(8_000),
    idempotency_key: z.string().trim().min(1).max(255),
  })
  .strict();
export type ChatRequestInput = z.input<typeof ChatRequestSchema>;
export type ChatRequest = z.infer<typeof ChatRequestSchema>;

export const ChatResponseSchema = z.object({
  conversation_id: uuidSchema,
  message_id: uuidSchema,
  status: z.enum(["ok", "insufficient_material"]),
  answer_blocks: z.array(GroundedContentBlockSchema),
  citations: z.array(CitationSchema),
  suggested_actions: z.array(SuggestedActionSchema),
});
export type ChatResponse = z.infer<typeof ChatResponseSchema>;
