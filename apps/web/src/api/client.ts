import type { z } from "zod";

import {
  ApiErrorResponseSchema,
  type PublicErrorCode,
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
