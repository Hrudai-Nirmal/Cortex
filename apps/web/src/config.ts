/** Build-surface configuration keeps split frontend deployments deterministic. */

import type { Surface } from "./types";

const DEFAULT_QUERY_PUBLIC_URL = "http://127.0.0.1:5174";
const DEFAULT_CONSOLE_PUBLIC_URL = "http://127.0.0.1:5173";
const RESERVED_DOCUMENTATION_HOST_SUFFIXES = [
  "example.com",
  "example.org",
  "example.net",
  "example.test",
] as const;

function isReservedDocumentationHost(hostName: string): boolean {
  const normalizedHost = hostName.trim().toLowerCase();
  return RESERVED_DOCUMENTATION_HOST_SUFFIXES.some(
    (suffix) => normalizedHost === suffix || normalizedHost.endsWith(`.${suffix}`),
  );
}

function validateSurfacePublicUrl(
  urlValue: string,
  surfaceLabel: "console" | "query",
  isProductionBuild: boolean,
): string {
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(urlValue);
  } catch {
    throw new Error(`Cortex ${surfaceLabel} public URL must be an absolute http(s) URL.`);
  }
  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    throw new Error(`Cortex ${surfaceLabel} public URL must use http or https.`);
  }
  if (
    !["", "/"].includes(parsedUrl.pathname)
    || parsedUrl.search
    || parsedUrl.hash
    || parsedUrl.username
    || parsedUrl.password
  ) {
    throw new Error(
      `Cortex ${surfaceLabel} public URL must stay rooted at the host with no path, query, fragment, or embedded credentials.`,
    );
  }
  if (isProductionBuild) {
    if (parsedUrl.protocol !== "https:") {
      throw new Error(`Production Cortex ${surfaceLabel} public URL must use https.`);
    }
    if (["localhost", "127.0.0.1", "::1"].includes(parsedUrl.hostname)) {
      throw new Error(`Production Cortex ${surfaceLabel} public URL must not use localhost.`);
    }
    if (isReservedDocumentationHost(parsedUrl.hostname)) {
      throw new Error(
        `Production Cortex ${surfaceLabel} public URL must not use documentation placeholder domains.`,
      );
    }
  }
  return urlValue.replace(/\/$/, "");
}

/** Resolve one Cortex browser-surface public URL from Vite env with package-safe validation. */
export function resolveSurfacePublicUrl(
  configuredUrl: string | undefined,
  defaultUrl: string,
  surfaceLabel: "console" | "query",
  isProductionBuild: boolean,
): string {
  const normalizedUrl = String(configuredUrl || "").trim();
  if (!normalizedUrl) {
    if (isProductionBuild) {
      throw new Error(
        `Production Cortex ${surfaceLabel} build is missing ${surfaceLabel === "console" ? "VITE_CORTEX_CONSOLE_PUBLIC_URL" : "VITE_CORTEX_QUERY_PUBLIC_URL"}.`,
      );
    }
    return defaultUrl;
  }
  return validateSurfacePublicUrl(normalizedUrl, surfaceLabel, isProductionBuild);
}

/** Resolve the packaged Cortex browser surface from Vite env with production validation. */
export function resolveSurface(
  configuredSurface: string | undefined,
  isProductionBuild: boolean,
): Surface {
  if (configuredSurface === "query") {
    return "query";
  }
  if (configuredSurface === "developer") {
    return "developer";
  }
  if (isProductionBuild) {
    throw new Error(
      "Production Cortex frontend build is missing VITE_CORTEX_SURFACE=developer|query.",
    );
  }
  return "developer";
}

/** Resolve the current built Cortex surface from Vite environment settings. */
export function getActiveSurface(): Surface {
  return resolveSurface(import.meta.env.VITE_CORTEX_SURFACE, Boolean(import.meta.env.PROD));
}

/** Return the configured public query URL used for cross-surface navigation. */
export function getQueryPublicUrl(): string {
  return resolveSurfacePublicUrl(
    import.meta.env.VITE_CORTEX_QUERY_PUBLIC_URL,
    DEFAULT_QUERY_PUBLIC_URL,
    "query",
    Boolean(import.meta.env.PROD),
  );
}

/** Return the configured public console URL used for operator access links. */
export function getConsolePublicUrl(): string {
  return resolveSurfacePublicUrl(
    import.meta.env.VITE_CORTEX_CONSOLE_PUBLIC_URL,
    DEFAULT_CONSOLE_PUBLIC_URL,
    "console",
    Boolean(import.meta.env.PROD),
  );
}
