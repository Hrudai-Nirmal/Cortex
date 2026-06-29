/** Shared navigation keeps surface switching explicit without exposing operator tools to employees. */

import { useEffect, useState } from "react";
import {
  ArrowsLeftRight,
  BookOpenText,
  ChartLineUp,
  ChatCircleDots,
  Database,
  FileMagnifyingGlass,
  Gauge,
  GearSix,
  Graph,
  UserCircle,
} from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { getQueryPublicUrl } from "../config";
import { getSession, getStartupHealth } from "../lib/api-client";
import type { DeveloperWorkspaceTab, RuntimeHealth, Session, Surface } from "../types";

interface AppNavigationProps {
  activeSurface: Surface;
  onSurfaceChange?: (surface: Surface) => void;
  activeDeveloperSection?: DeveloperWorkspaceTab;
  onDeveloperSectionChange?: (section: DeveloperWorkspaceTab) => void;
}

interface NavItem {
  label: string;
  icon: Icon;
  section: DeveloperWorkspaceTab;
}

const developerItems: NavItem[] = [
  { label: "Graph", icon: Graph, section: "Graph" },
  { label: "Sources", icon: Database, section: "Sources" },
  { label: "Jobs", icon: ArrowsLeftRight, section: "Jobs" },
  { label: "Configuration", icon: Gauge, section: "Configuration" },
  { label: "Evaluations", icon: ChartLineUp, section: "Evaluations" },
  { label: "Versions", icon: FileMagnifyingGlass, section: "Versions" },
];

const governanceItems: NavItem[] = [
  { label: "Settings", icon: GearSix, section: "Settings" },
];

function getRuntimeQueryPublicUrl(runtimeHealth: RuntimeHealth | null): string | null {
  const deploymentConfig = runtimeHealth?.components.find(
    (component) => component.name === "deployment-config",
  );
  if (!deploymentConfig?.detail) {
    return null;
  }
  const queryMatch = deploymentConfig.detail.match(/query=([^,]+), cors=/);
  return queryMatch?.[1] ?? null;
}

function renderNavItem(
  item: NavItem,
  activeDeveloperSection: DeveloperWorkspaceTab,
  onDeveloperSectionChange?: (section: DeveloperWorkspaceTab) => void,
) {
  const ItemIcon = item.icon;
  const isActive = item.section === activeDeveloperSection;
  return (
    <button
      aria-current={isActive ? "page" : undefined}
      className={`nav-item${isActive ? " nav-item--active" : ""}`}
      key={item.label}
      type="button"
      onClick={() => onDeveloperSectionChange?.(item.section)}
    >
      <ItemIcon aria-hidden size={17} weight={isActive ? "duotone" : "regular"} />
      <span>{item.label}</span>
    </button>
  );
}

/** Render navigation appropriate to the currently selected product surface. */
export function AppNavigation({
  activeSurface,
  onSurfaceChange,
  activeDeveloperSection = "Graph",
  onDeveloperSectionChange,
}: AppNavigationProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [runtimeQueryPublicUrl, setRuntimeQueryPublicUrl] = useState<string | null>(null);
  const fallbackQueryPublicUrl = getQueryPublicUrl();

  useEffect(() => {
    let isMounted = true;

    async function loadNavigationContext(): Promise<void> {
      try {
        const sessionPromise = getSession();
        const startupHealthPromise =
          activeSurface === "developer" ? getStartupHealth() : Promise.resolve(null);
        const [resolvedSession, startupHealth] = await Promise.all([
          sessionPromise,
          startupHealthPromise,
        ]);
        if (!isMounted) {
          return;
        }
        setSession(resolvedSession);
        setRuntimeQueryPublicUrl(getRuntimeQueryPublicUrl(startupHealth));
      } catch {
        if (isMounted) {
          setSession(null);
          setRuntimeQueryPublicUrl(null);
        }
      }
    }

    void loadNavigationContext();
    return () => {
      isMounted = false;
    };
  }, [activeSurface]);

  if (activeSurface === "query") {
    return (
      <aside className="query-navigation">
        <button
          className="brand brand--button"
          type="button"
          onClick={() => onSurfaceChange?.("query")}
        >
          Cortex
        </button>
        <nav aria-label="Employee query navigation" className="query-navigation__links">
          <button className="query-navigation__item query-navigation__item--active" type="button">
            <ChatCircleDots aria-hidden size={19} weight="duotone" /> Ask Cortex
          </button>
          <button className="query-navigation__item" type="button">
            <BookOpenText aria-hidden size={19} /> My conversations
          </button>
        </nav>
        <div className="query-navigation__footer">
          <button className="query-navigation__item" type="button">
            <GearSix aria-hidden size={19} /> Preferences
          </button>
          <div className="identity-row">
            <UserCircle aria-hidden size={30} weight="duotone" />
            <div>
              <strong>{session?.displayName ?? "Loading identity"}</strong>
              <span>{session?.roles[0] ?? "Employee"}</span>
            </div>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="developer-navigation">
      <div className="brand">Cortex</div>
      <div className="nav-section-label">Operations</div>
      <nav aria-label="Developer operations">
        {developerItems.map((item) =>
          renderNavItem(item, activeDeveloperSection, onDeveloperSectionChange),
        )}
      </nav>
      <div className="nav-section-label nav-section-label--spaced">Governance</div>
      <nav aria-label="Governance">
        {governanceItems.map((item) =>
          renderNavItem(item, activeDeveloperSection, onDeveloperSectionChange),
        )}
      </nav>
      <div className="developer-navigation__footer">
        <a className="surface-switch" href={runtimeQueryPublicUrl ?? fallbackQueryPublicUrl}>
          <ChatCircleDots aria-hidden size={17} /> Open employee view
        </a>
        <div className="identity-row">
          <UserCircle aria-hidden size={30} weight="duotone" />
          <div>
            <strong>{session?.displayName ?? "Loading identity"}</strong>
            <span>{session?.roles.join(", ") ?? "Platform admin"}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
