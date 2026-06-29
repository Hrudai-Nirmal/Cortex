/** Navigation tests keep cross-surface links aligned with live packaged deployment config. */

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppNavigation } from "./app-navigation";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("AppNavigation", () => {
  it("routes developer navigation clicks through the shared workspace callback", async () => {
    const handleDeveloperSectionChange = vi.fn();

    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            actorId: "alex.rivera@example.com",
            subject: "alex.rivera@example.com",
            email: "alex.rivera@example.com",
            displayName: "Alex Rivera",
            groups: ["group:employees", "group:platform-admins"],
            roles: ["admin", "builder"],
            principalIds: ["group:employees", "group:platform-admins", "role:admin", "role:builder"],
            isAdmin: true,
            isBuilder: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "ready",
            environment: "production",
            components: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(
      <AppNavigation
        activeSurface="developer"
        activeDeveloperSection="Graph"
        onDeveloperSectionChange={handleDeveloperSectionChange}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Sources" }));

    expect(handleDeveloperSectionChange).toHaveBeenCalledWith("Sources");
  });

  it("prefers the runtime query public URL from startup health over baked frontend defaults", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            actorId: "alex.rivera@example.com",
            subject: "alex.rivera@example.com",
            email: "alex.rivera@example.com",
            displayName: "Alex Rivera",
            groups: ["group:employees", "group:platform-admins"],
            roles: ["admin", "builder"],
            principalIds: ["group:employees", "group:platform-admins", "role:admin", "role:builder"],
            isAdmin: true,
            isBuilder: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "ready",
            environment: "production",
            components: [
              {
                name: "deployment-config",
                status: "ready",
                severity: "info",
                detail:
                  "console=https://cortex-console.client.internal, query=https://cortex-app.client.internal, cors=https://cortex-console.client.internal, https://cortex-app.client.internal, startupPolicy=fail-closed",
                remediation: null,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<AppNavigation activeSurface="developer" />);

    const employeeLink = await screen.findByRole("link", { name: "Open employee view" });
    expect(employeeLink).toHaveAttribute("href", "https://cortex-app.client.internal");
  });
});
