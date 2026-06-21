/** Shared Vite settings for split Cortex frontend builds. */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export function createSurfaceConfig({
  outDir,
  port,
  root,
  surface,
}) {
  return defineConfig({
    define: {
      "import.meta.env.VITE_CORTEX_SURFACE": JSON.stringify(surface),
    },
    optimizeDeps: {
      include: ["react", "react-dom/client"],
    },
    plugins: [react()],
    root,
    server: {
      host: "127.0.0.1",
      port,
      proxy: {
        "/v1": "http://127.0.0.1:8000",
        "/health": "http://127.0.0.1:8000",
      },
      warmup: {
        clientFiles: [
          surface === "developer" ? "../src/console-main.tsx" : "../src/query-main.tsx",
        ],
      },
    },
    build: {
      outDir,
      emptyOutDir: true,
    },
  });
}
