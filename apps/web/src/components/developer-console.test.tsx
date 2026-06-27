/** Developer console tests verify the live trace timeline wiring stays visible to builders. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeveloperConsole } from "./developer-console";

class MockEventSource {
  listeners: Record<string, Array<(event: MessageEvent<string>) => void>> = {};

  addEventListener(eventName: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners[eventName] = [...(this.listeners[eventName] ?? []), listener];
  }

  close(): void {
    return;
  }
}

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", MockEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("DeveloperConsole", () => {
  it("loads the active pipeline and latest persisted trace", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            name: "Enterprise evidence pipeline",
            version: 3,
            status: "active",
            rerankTopK: 40,
            nodes: [],
            edges: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              pipelineVersionId: "e5165ff1-a5ee-48dd-a8b2-c955153bd837",
              enterpriseId: "00000000-0000-0000-0000-000000000001",
              version: 4,
              status: "validated",
              createdBy: "alex.rivera@example.com",
              createdAt: "2026-06-22T00:00:00+00:00",
              activatedAt: null,
              rerankTopK: 40,
              definitionHash: "8d24df0a6d7e39c0ec9f6a2f7c1b66f1",
            },
            {
              pipelineVersionId: "e5165ff1-a5ee-48dd-a8b2-c955153bd838",
              enterpriseId: "00000000-0000-0000-0000-000000000001",
              version: 3,
              status: "active",
              createdBy: "alex.rivera@example.com",
              createdAt: "2026-06-21T00:00:00+00:00",
              activatedAt: "2026-06-21T00:00:00+00:00",
              rerankTopK: 40,
              definitionHash: "7d24df0a6d7e39c0ec9f6a2f7c1b66f0",
            },
            {
              pipelineVersionId: "e5165ff1-a5ee-48dd-a8b2-c955153bd839",
              enterpriseId: "00000000-0000-0000-0000-000000000001",
              version: 2,
              status: "retired",
              createdBy: "maya.chen@example.com",
              createdAt: "2026-06-20T00:00:00+00:00",
              activatedAt: "2026-06-20T00:00:00+00:00",
              rerankTopK: 30,
              definitionHash: "6d24df0a6d7e39c0ec9f6a2f7c1b66ef",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "ready",
            environment: "development",
            components: [
              {
                name: "deployment-config",
                status: "ready",
                severity: "info",
                detail:
                  "console=https://cortex-console.hrudainirmal.in, query=https://cortex-app.hrudainirmal.in, cors=https://cortex-console.hrudainirmal.in, https://cortex-app.hrudainirmal.in, startupPolicy=fail-closed, querySurfaceMode=bundled",
                remediation: null,
              },
              {
                name: "object-storage",
                status: "ready",
                severity: "info",
                detail: "/var/lib/cortex/object-storage (read/write probe ok)",
                remediation: null,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "degraded",
            environment: "development",
            components: [
              {
                name: "model-profile",
                status: "ready",
                severity: "info",
                detail: "generator=qwen3:14b, embedding=qwen3-embedding:0.6b, requiredAccelerator=cpu",
                remediation: "Keep this profile aligned with the client deployment agreement.",
              },
              {
                name: "package-build-profile",
                status: "ready",
                severity: "info",
                detail: "torchWheelIndex=https://download.pytorch.org/whl/cpu, preinstall=torch torchvision, requiredAccelerator=cpu",
                remediation: "Keep this build profile aligned with the package image that was built for the client deployment target.",
              },
              {
                name: "identity-profile",
                status: "ready",
                severity: "info",
                detail: "authMode=fixture, oidcIssuer=https://cortex.local/oidc, oidcAudience=cortex",
                remediation: "Verify that bearer tokens reaching Cortex match the declared issuer and audience.",
              },
              { name: "postgresql", status: "ready", severity: "info", detail: "database ready", remediation: null },
              { name: "ollama", status: "ready", severity: "info", detail: "ollama models ready", remediation: null },
              {
                name: "model-endpoint-policy",
                status: "degraded",
                severity: "error",
                detail: "model endpoint host example.com is not local or private",
                remediation: "Point CORTEX_OLLAMA_BASE_URL at a local endpoint.",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            traceId: "4576b626-c27a-4409-9a51-600cf115ff4a",
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            actorId: "maya.chen@example.com",
            route: "rag",
            rawQuery: "What are our retention rules?",
            correctedQuery: "What are our retention rules?",
            answer: "Raw query and response content is retained for 30 days.",
            evidenceStatus: "sufficient",
            createdAt: "2026-06-21T00:00:00+00:00",
            claims: [
              {
                claimId: "claim-1",
                text: "Raw query and response content is retained for 30 days.",
                confidence: 0.98,
                citationIds: ["C1"],
                supportStatus: "supported",
              },
            ],
            citations: [
              {
                citationId: "C1",
                documentTitle: "Security Handbook",
                documentVersion: "v2",
                chunkId: "abc123",
                structuralLocator: "p.12",
                exactSpan: "Raw query and response content is retained for 30 days.",
                supportScore: 0.98,
              },
            ],
            stages: [],
            stageEvents: [
              {
                traceId: "4576b626-c27a-4409-9a51-600cf115ff4a",
                stage: "Scoped hybrid retrieval",
                position: 2,
                status: "complete",
                detail: "4 authorized candidates after threshold",
                durationMs: 120,
              },
            ],
            retrievedEvidence: [
              {
                chunkId: "abc123",
                documentTitle: "Security Handbook",
                documentVersion: "v2",
                structuralLocator: "p.12",
                supportScore: 0.98,
                sourceScore: 0.96,
                rerankScore: 0.99,
                contentPreview: "Raw query and response content is retained for 30 days.",
              },
            ],
            pipelineVersion: 3,
            outcome: "sufficient",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            contractVersion: "v1",
            endpointPath: "/v1/chat/completions",
            method: "POST",
            authentication: "bearer-token",
            supportsStreaming: false,
            requestOptions: {
              userMessageSelectionPolicy: "last-non-empty-user-message",
              streamRequiredValue: false,
              supportsCitationToggle: true,
            },
            querySurfaceMode: "bundled",
            bundledQueryUiAvailable: true,
            traceEventsPathTemplate: "/v1/query/{traceId}/events",
            operatorConsolePath: "/developer",
            responseHeaders: [
              "X-Cortex-Contract-Version",
              "X-Cortex-Trace-Id",
              "X-Cortex-Evidence-Status",
              "X-Cortex-Route",
              "X-Cortex-Abstained",
            ],
            extensionFields: [
              "contractVersion",
              "traceId",
              "traceEventsPath",
              "route",
              "correctedQuery",
              "evidenceStatus",
              "abstained",
              "claims",
              "citations",
              "stages",
            ],
            employeeSafeExtensionFields: [
              "contractVersion",
              "traceId",
              "route",
              "correctedQuery",
              "evidenceStatus",
              "abstained",
              "claims",
              "citations",
              "stages",
            ],
            operatorOnlyExtensionFields: ["traceEventsPath"],
            errorStatuses: [
              {
                statusCode: 422,
                code: "invalid_request",
                retryable: false,
                meaning:
                  "The request shape violates the stable Cortex query facade, for example no usable user message or stream=true.",
              },
              {
                statusCode: 403,
                code: "forbidden_scope",
                retryable: false,
                meaning:
                  "The authenticated identity is not allowed to access the requested enterprise scope or sources.",
              },
              {
                statusCode: 503,
                code: "provider_unavailable",
                retryable: true,
                meaning:
                  "A required local provider such as the configured model endpoint was unavailable or timed out during deterministic execution.",
              },
              {
                statusCode: 500,
                code: "internal_error",
                retryable: true,
                meaning:
                  "Cortex failed outside the expected validation, authorization, or provider error contract.",
              },
            ],
            evidenceStatuses: ["sufficient", "partial", "insufficient", "conflict"],
            routes: ["rag", "compute", "retrieve-then-compute"],
            abstentionEvidenceStatuses: ["insufficient", "conflict"],
            notes: [
              "Use the last non-empty user message as the deterministic query input.",
              "Do not send raw enterprise scope or ACL principals from the browser; Cortex derives them from the bearer token.",
              "Treat traceEventsPath as an operator-grade debugging surface rather than a standard employee UI dependency.",
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
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
      );

    render(<DeveloperConsole />);

    expect(await screen.findByRole("heading", { name: "Enterprise evidence pipeline" })).toBeVisible();
    expect(screen.getByText("What are our retention rules?")).toBeVisible();
    expect(screen.getByText("maya.chen@example.com")).toBeVisible();
    expect(screen.getByText("degraded")).toBeVisible();
    expect(screen.getByText("Validated answer preview")).toBeVisible();
    expect(screen.getByText("Operator correlation")).toBeVisible();
    expect(screen.getAllByText("Security Handbook")).toHaveLength(2);
    expect(screen.getByText("supported")).toBeVisible();
    expect(screen.getByText("Evidence chunk")).toBeVisible();
    expect(
      screen.getAllByText("Raw query and response content is retained for 30 days."),
    ).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("Client query contract")).toBeVisible();
    expect(screen.getByText("Bundled employee shell")).toBeVisible();
    expect(screen.getAllByText("This package ships the built-in query-web employee UI.").length).toBeGreaterThan(0);
    expect(screen.getByText("Contract headers")).toBeVisible();
    expect(screen.getByText("Request behavior")).toBeVisible();
    expect(screen.getByText("Employee-safe fields")).toBeVisible();
    expect(screen.getByText("Operator-only fields")).toBeVisible();
    expect(screen.getByText("Error statuses")).toBeVisible();
    expect(screen.getByText("X-Cortex-Route")).toBeVisible();
    expect(screen.getByText("X-Cortex-Abstained")).toBeVisible();
    expect(screen.getByText("last-non-empty-user-message")).toBeVisible();
    expect(screen.getByText("provider_unavailable")).toBeVisible();
    expect(screen.getByText("Contract guidance")).toBeVisible();
    expect(screen.getAllByText("x_cortex.traceEventsPath")).toHaveLength(2);
    expect(screen.getByText("insufficient")).toBeVisible();
    expect(screen.getByText("Model profile")).toBeVisible();
    expect(screen.getByText("Package build profile")).toBeVisible();
    expect(screen.getByText("Identity profile")).toBeVisible();
    expect(screen.getByText("Startup contract")).toBeVisible();
    expect(screen.getByText("Live readiness")).toBeVisible();
    expect(screen.getByText("Static package startup contract is satisfied.")).toBeVisible();
    expect(screen.getByText("Operator action queue")).toBeVisible();
    expect(screen.getByText("Runtime alert · model-endpoint-policy")).toBeVisible();
    expect(screen.getAllByText("Point CORTEX_OLLAMA_BASE_URL at a local endpoint.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("generator=qwen3:14b, embedding=qwen3-embedding:0.6b, requiredAccelerator=cpu")).toHaveLength(2);
    expect(
      screen.getAllByText(
        "torchWheelIndex=https://download.pytorch.org/whl/cpu, preinstall=torch torchvision, requiredAccelerator=cpu",
      ),
    ).toHaveLength(2);
    expect(screen.getAllByText("authMode=fixture, oidcIssuer=https://cortex.local/oidc, oidcAudience=cortex")).toHaveLength(2);
    expect(screen.getByText("Surface routing")).toBeVisible();
    expect(screen.getByText("Surface deployment contract")).toBeVisible();
    expect(screen.getByText("Browser host split")).toBeVisible();
    expect(screen.getByText("Startup policy")).toBeVisible();
    expect(screen.getByText("Query contract handshake")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Versions" }));
    expect(await screen.findByText("Lifecycle queue")).toBeVisible();
    expect(screen.getByText("Promote validated version")).toBeVisible();
    expect(screen.getByText("Version v4 is validated and waiting for activation into the live query path.")).toBeVisible();
    expect(screen.getByText("Keep rollback candidate ready")).toBeVisible();
    expect(screen.getByText("Version v2 remains available for explicit rollback if the active release regresses.")).toBeVisible();
    expect(await screen.findByText("Rollback ready")).toBeVisible();
    expect(screen.getByRole("button", { name: "Promote" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Roll back" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(7));
  });

  it("keeps the console usable when the external query contract endpoint is unavailable", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            name: "Enterprise evidence pipeline",
            version: 3,
            status: "active",
            rerankTopK: 40,
            nodes: [],
            edges: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "degraded",
            environment: "production",
            components: [
              {
                name: "deployment-config",
                status: "ready",
                severity: "info",
                detail:
                  "console=https://cortex-console.hrudainirmal.in, query=https://cortex-app.hrudainirmal.in, cors=https://cortex-console.hrudainirmal.in, https://cortex-app.hrudainirmal.in, startupPolicy=fail-closed, querySurfaceMode=external",
                remediation: null,
              },
              {
                name: "object-storage",
                status: "unavailable",
                severity: "error",
                detail: "object storage root is not writable",
                remediation: "Mount a writable persistent volume before boot.",
              },
            ],
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
                  "console=https://cortex-console.hrudainirmal.in, query=https://cortex-app.hrudainirmal.in, cors=https://cortex-console.hrudainirmal.in, https://cortex-app.hrudainirmal.in, startupPolicy=fail-closed, querySurfaceMode=external",
                remediation: null,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(null), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Request failed with status 503" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      )
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
      );

    render(<DeveloperConsole />);

    expect(await screen.findByRole("heading", { name: "Enterprise evidence pipeline" })).toBeVisible();
    expect(screen.getByText("Some operator data is unavailable: Query contract: Request failed with status 503")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("Surface deployment contract")).toBeVisible();
    expect(screen.getByText("External client-owned employee shell")).toBeVisible();
    expect(screen.getAllByText("This package exposes the query host as an API-only surface for a client-owned employee UI.").length).toBeGreaterThan(0);
    expect(screen.getByText("Fail-closed startup gate")).toBeVisible();
    expect(screen.getByText("Startup contract")).toBeVisible();
    expect(screen.getAllByText("degraded").length).toBeGreaterThan(0);
    expect(screen.getByText("Operator action queue")).toBeVisible();
    expect(screen.getByText("Startup gate · object-storage")).toBeVisible();
    expect(screen.getAllByText("Query contract handshake").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Restore GET /v1/chat/contracts/v1 so bundled and client-owned query UIs can verify the live Cortex contract before sending traffic.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("The live replacement-query contract descriptor is unavailable.").length).toBeGreaterThan(0);
  });
});
