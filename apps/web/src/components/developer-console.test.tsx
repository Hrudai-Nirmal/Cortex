/** Developer console tests verify the live trace timeline wiring stays visible to builders. */

import { render, screen, waitFor } from "@testing-library/react";
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
              version: 3,
              status: "active",
              createdBy: "alex.rivera@example.com",
              createdAt: "2026-06-21T00:00:00+00:00",
              activatedAt: "2026-06-21T00:00:00+00:00",
              rerankTopK: 40,
              definitionHash: "7d24df0a6d7e39c0ec9f6a2f7c1b66f0",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "degraded",
            environment: "development",
            components: [
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
            citations: [],
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
            pipelineVersion: 3,
            outcome: "sufficient",
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
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
  });
});
