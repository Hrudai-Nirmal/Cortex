/** Bootstraps the dedicated Cortex console build. */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@xyflow/react/dist/style.css";
import { ConsoleRoot } from "./console-root";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Cortex console root element was not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <ConsoleRoot />
  </StrictMode>,
);
