/** Vite configuration for the dedicated Cortex console build. */

import { fileURLToPath } from "node:url";
import path from "node:path";
import { createSurfaceConfig } from "./vite.shared.config.mjs";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));

export default createSurfaceConfig({
  root: path.resolve(currentDirectory, "console"),
  outDir: path.resolve(currentDirectory, "dist-console"),
  port: 5173,
  surface: "developer",
});
