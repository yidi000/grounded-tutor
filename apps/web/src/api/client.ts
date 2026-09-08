import { z } from "zod";

import {
  ApiErrorResponseSchema,
  ChatResponseSchema,
  ChatHistoryResponseSchema,
  PreviewResponseSchema,
  ProcessedPreviewResponseSchema,
  SourceIngestionResponseSchema,
  SourceResponseSchema,
  WorkspaceResponseSchema,
  type PublicErrorCode,
  type ChunkSettings,
  type ChatRequest,
  type WorkspaceCreate,
  type WorkspaceUpdate,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: PublicErrorCode,
  ) {
    super(code);
  }
}

export async function apiFetch<T>(
  schema: z.ZodType<T>,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
  let requestInit = init;
  if (typeof init?.body === "string") {
    const headers = new Headers(init.headers);
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    requestInit = { ...init, headers };
  }

  const response = await fetch(input, requestInit);
  if (!response.ok) {
    let code: PublicErrorCode = "external_service_error";
    try {
      const error = ApiErrorResponseSchema.safeParse(await response.json());
      if (error.success) code = error.data.detail.code;
    } catch {
      // The stable fallback keeps private response content out of the Error.
    }
    throw new ApiError(response.status, code);
  }
  return schema.parse(await response.json());
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
});

export const api = {
  listWorkspaces: (signal?: AbortSignal) =>
    apiFetch(z.array(WorkspaceResponseSchema), "/api/workspaces", { signal }),
  deleteWorkspace: async (id: string) => {
    const response = await fetch(`/api/workspaces/${id}`, { method: "DELETE" });
    if (!response.ok) throw new ApiError(response.status, "external_service_error");
  },
  createWorkspace: (payload: Pick<WorkspaceCreate, "title"> & Partial<Omit<WorkspaceCreate, "title">>) =>
    apiFetch(WorkspaceResponseSchema, "/api/workspaces", json(payload)),
  renameWorkspace: (id: string, payload: WorkspaceUpdate) =>
    apiFetch(WorkspaceResponseSchema, `/api/workspaces/${id}`, {
      ...json(payload),
      method: "PATCH",
    }),
  listSources: (workspaceId: string, signal?: AbortSignal) =>
    apiFetch(
      z.array(SourceResponseSchema),
      `/api/workspaces/${workspaceId}/sources`,
      { signal },
    ),
  previewText: (
    workspaceId: string,
    sourceName: string,
    text: string,
    settings: ChunkSettings,
  ) =>
    apiFetch(
      PreviewResponseSchema,
      `/api/workspaces/${workspaceId}/source-previews/text`,
      json({ source_name: sourceName, text, settings }),
    ),
  previewFile: (
    workspaceId: string,
    file: File,
    settings: ChunkSettings,
  ) => {
    const body = new FormData();
    body.set("file", file);
    body.set("settings", JSON.stringify(settings));
    return apiFetch(
      PreviewResponseSchema,
      `/api/workspaces/${workspaceId}/source-previews/file`,
      { method: "POST", body },
    );
  },
  ingestText: (
    workspaceId: string,
    sourceName: string,
    text: string,
    settings: ChunkSettings,
    replaces?: string,
  ) =>
    apiFetch(
      SourceIngestionResponseSchema,
      replaces
        ? `/api/workspaces/${workspaceId}/sources/${replaces}/reprocess/text`
        : `/api/workspaces/${workspaceId}/sources/text`,
      json({ source_name: sourceName, text, settings }),
    ),
  ingestFile: (
    workspaceId: string,
    file: File,
    settings: ChunkSettings,
    replaces?: string,
  ) => {
    const body = new FormData();
    body.set("file", file);
    body.set("settings", JSON.stringify(settings));
    return apiFetch(
      SourceIngestionResponseSchema,
      replaces
        ? `/api/workspaces/${workspaceId}/sources/${replaces}/reprocess/file`
        : `/api/workspaces/${workspaceId}/sources/file`,
      { method: "POST", body },
    );
  },
  processedPreview: (workspaceId: string, sourceId: string) =>
    apiFetch(
      ProcessedPreviewResponseSchema,
      `/api/workspaces/${workspaceId}/sources/${sourceId}/processed-preview`,
    ),
  acceptSource: (workspaceId: string, sourceId: string) =>
    apiFetch(
      SourceResponseSchema,
      `/api/workspaces/${workspaceId}/sources/${sourceId}/accept`,
      { method: "POST" },
    ),
  deleteSource: async (workspaceId: string, sourceId: string) => {
    const response = await fetch(
      `/api/workspaces/${workspaceId}/sources/${sourceId}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      let code: PublicErrorCode = "external_service_error";
      try {
        const parsed = ApiErrorResponseSchema.safeParse(await response.json());
        if (parsed.success) code = parsed.data.detail.code;
      } catch {
        // Keep provider content private.
      }
      throw new ApiError(response.status, code);
    }
  },
  chatHistory: (workspaceId: string, signal?: AbortSignal) =>
    apiFetch(ChatHistoryResponseSchema, `/api/workspaces/${workspaceId}/chat/history`, { signal }),
  ask: (workspaceId: string, payload: ChatRequest) =>
    apiFetch(
      ChatResponseSchema,
      `/api/workspaces/${workspaceId}/chat`,
      json(payload),
    ),
};
