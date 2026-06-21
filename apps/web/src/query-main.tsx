/** Bootstraps the dedicated Cortex query-app build. */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryRoot } from "./query-root";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Cortex query root element was not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryRoot />
  </StrictMode>,
);
