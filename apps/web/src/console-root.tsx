/** Console-root renders the fixed operator-facing Cortex console surface. */

import { AppNavigation } from "./components/app-navigation";
import { DeveloperConsole } from "./components/developer-console";

/** Render the immutable developer console shipped with every Cortex deployment. */
export function ConsoleRoot() {
  return (
    <div className="app-frame app-frame--developer">
      <AppNavigation activeSurface="developer" />
      <DeveloperConsole />
    </div>
  );
}
