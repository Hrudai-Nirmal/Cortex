/** Vite configuration for the dedicated Cortex query-app build. */

import { fileURLToPath } from "node:url";
import path from "node:path";
import { createSurfaceConfig } from "./vite.shared.config.mjs";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));

export default createSurfaceConfig({
  root: path.resolve(currentDirectory, "query"),
  outDir: path.resolve(currentDirectory, "dist-query"),
  port: 5174,
  surface: "query",
});
