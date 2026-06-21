/** Build-surface configuration keeps split frontend deployments deterministic. */

import type { Surface } from "./types";

const DEFAULT_QUERY_PUBLIC_URL = "http://127.0.0.1:5174";
const DEFAULT_CONSOLE_PUBLIC_URL = "http://127.0.0.1:5173";

/** Resolve the current built Cortex surface from Vite environment settings. */
export function getActiveSurface(): Surface {
  return import.meta.env.VITE_CORTEX_SURFACE === "query" ? "query" : "developer";
}

/** Return the configured public query URL used for cross-surface navigation. */
export function getQueryPublicUrl(): string {
  return (
    String(import.meta.env.VITE_CORTEX_QUERY_PUBLIC_URL || "").trim() ||
    DEFAULT_QUERY_PUBLIC_URL
  );
}

/** Return the configured public console URL used for operator access links. */
export function getConsolePublicUrl(): string {
  return (
    String(import.meta.env.VITE_CORTEX_CONSOLE_PUBLIC_URL || "").trim() ||
    DEFAULT_CONSOLE_PUBLIC_URL
  );
}
