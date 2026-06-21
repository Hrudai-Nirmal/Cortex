/** Selects the intentionally separate developer and employee product surfaces. */

import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AppNavigation } from "./components/app-navigation";
import type { Surface } from "./types";

const DeveloperConsole = lazy(async () => {
  try {
    const module = await import("./components/developer-console");
    return { default: module.DeveloperConsole };
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : "Developer console failed to load");
  }
});

const EndUserQuery = lazy(async () => {
  try {
    const module = await import("./components/end-user-query");
    return { default: module.EndUserQuery };
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : "Employee query failed to load");
  }
});

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeSurface: Surface = location.pathname.startsWith("/ask") ? "query" : "developer";

  function handleSurfaceChange(surface: Surface): void {
    navigate(surface === "developer" ? "/developer" : "/ask");
  }

  return (
    <div className={`app-frame app-frame--${activeSurface}`}>
      <AppNavigation activeSurface={activeSurface} onSurfaceChange={handleSurfaceChange} />
      <Suspense fallback={<main className="surface-loading">Loading Cortex…</main>}>
        <Routes>
          <Route path="/developer" element={<DeveloperConsole />} />
          <Route path="/ask" element={<EndUserQuery />} />
          <Route path="*" element={<Navigate to="/developer" replace />} />
        </Routes>
      </Suspense>
    </div>
  );
}
