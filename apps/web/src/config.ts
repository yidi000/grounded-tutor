export type AppMode = "local" | "demo_read_only";

export function parseAppMode(value: unknown): AppMode {
  if (value === "local" || value === "demo_read_only") {
    return value;
  }
  throw new Error("VITE_APP_MODE must be local or demo_read_only");
}
