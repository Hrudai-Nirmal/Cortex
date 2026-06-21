/** Query-root renders the employee-facing built-in Cortex query surface. */

import { AppNavigation } from "./components/app-navigation";
import { EndUserQuery } from "./components/end-user-query";

/** Render the optional bundled query UI that clients may replace with their own shell. */
export function QueryRoot() {
  return (
    <div className="app-frame app-frame--query">
      <AppNavigation activeSurface="query" />
      <EndUserQuery />
    </div>
  );
}
