/** Surface configuration tests keep packaged frontend builds from silently shipping dev URLs. */

import { describe, expect, it } from "vitest";
import { getConsolePublicUrl, getQueryPublicUrl, resolveSurface, resolveSurfacePublicUrl } from "./config";

describe("resolveSurfacePublicUrl", () => {
  it("keeps localhost defaults for development when no explicit public URL is set", () => {
    expect(
      resolveSurfacePublicUrl(undefined, "http://127.0.0.1:5174", "query", false),
    ).toBe("http://127.0.0.1:5174");
  });

  it("rejects missing production public URLs", () => {
    expect(() =>
      resolveSurfacePublicUrl(undefined, "http://127.0.0.1:5174", "query", true),
    ).toThrow("Production Cortex query surface is missing CORTEX_QUERY_PUBLIC_URL runtime config.");
  });

  it("rejects localhost, placeholder, and nested-path production URLs", () => {
    expect(() =>
      resolveSurfacePublicUrl("https://cortex-app.example.com", "http://127.0.0.1:5174", "query", true),
    ).toThrow("documentation placeholder domains");
    expect(() =>
      resolveSurfacePublicUrl("https://localhost", "http://127.0.0.1:5174", "query", true),
    ).toThrow("must not use localhost");
    expect(() =>
      resolveSurfacePublicUrl("https://cortex-app.client.internal/ask", "http://127.0.0.1:5174", "query", true),
    ).toThrow("must stay rooted at the host");
  });

  it("accepts real root-host https production URLs", () => {
    expect(
      resolveSurfacePublicUrl(
        "https://cortex-app.client.internal",
        "http://127.0.0.1:5174",
        "query",
        true,
      ),
    ).toBe("https://cortex-app.client.internal");
    expect(
      resolveSurfacePublicUrl(
        "https://cortex-console.client.internal/",
        "http://127.0.0.1:5173",
        "console",
        true,
      ),
    ).toBe("https://cortex-console.client.internal");
  });

  it("prefers runtime browser config over baked Vite defaults when present", () => {
    window.__CORTEX_RUNTIME_CONFIG__ = {
      consolePublicUrl: "https://cortex-console.client.internal",
      queryPublicUrl: "https://cortex-app.client.internal",
    };
    expect(getConsolePublicUrl()).toBe("https://cortex-console.client.internal");
    expect(getQueryPublicUrl()).toBe("https://cortex-app.client.internal");
    delete window.__CORTEX_RUNTIME_CONFIG__;
  });
});

describe("resolveSurface", () => {
  it("defaults to the developer surface in development when unset", () => {
    expect(resolveSurface(undefined, false)).toBe("developer");
  });

  it("rejects missing production surface declarations", () => {
    expect(() => resolveSurface(undefined, true)).toThrow(
      "Production Cortex frontend build is missing VITE_CORTEX_SURFACE=developer|query.",
    );
  });

  it("accepts both packaged surface variants", () => {
    expect(resolveSurface("developer", true)).toBe("developer");
    expect(resolveSurface("query", true)).toBe("query");
  });
});
