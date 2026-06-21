/// <reference types="vite/client" />

/** Vite env typing keeps split-surface builds type-safe across console and query apps. */

interface ImportMetaEnv {
  readonly VITE_CORTEX_CONSOLE_PUBLIC_URL?: string;
  readonly VITE_CORTEX_QUERY_PUBLIC_URL?: string;
  readonly VITE_CORTEX_SURFACE?: "developer" | "query";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
