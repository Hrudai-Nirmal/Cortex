/** Console-root renders the fixed operator-facing Cortex console surface. */

import { useState } from "react";
import { AppNavigation } from "./components/app-navigation";
import { DeveloperConsole } from "./components/developer-console";
import type { DeveloperWorkspaceTab } from "./types";

/** Render the immutable developer console shipped with every Cortex deployment. */
export function ConsoleRoot() {
  const [activeDeveloperSection, setActiveDeveloperSection] =
    useState<DeveloperWorkspaceTab>("Graph");

  return (
    <div className="app-frame app-frame--developer">
      <AppNavigation
        activeSurface="developer"
        activeDeveloperSection={activeDeveloperSection}
        onDeveloperSectionChange={setActiveDeveloperSection}
      />
      <DeveloperConsole
        activeTab={activeDeveloperSection}
        onActiveTabChange={setActiveDeveloperSection}
      />
    </div>
  );
}
