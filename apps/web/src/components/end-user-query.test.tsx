/** Employee query tests protect the simple UI and citation-display boundary. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EndUserQuery } from "./end-user-query";

const sessionResponse = {
  enterpriseId: "00000000-0000-0000-0000-000000000001",
  actorId: "maya.chen@example.com",
  subject: "maya.chen@example.com",
  email: "maya.chen@example.com",
  displayName: "Maya Chen",
  groups: ["group:employees"],
  roles: ["employee"],
  principalIds: ["group:employees", "role:employee"],
  isAdmin: false,
  isBuilder: false,
};

const contractResponse = {
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
  ],
};

const queryResponse = {
  id: "cortex-4576b626-c27a-4409-9a51-600cf115ff4a",
  object: "chat.completion",
  created: 1718928000,
  model: "cortex-bounded-rag",
  choices: [
    {
      index: 0,
      message: {
        role: "assistant",
        content: "Raw query content is retained for 30 days.",
      },
      finish_reason: "stop",
    },
  ],
  x_cortex: {
    contractVersion: "v1",
    traceId: "4576b626-c27a-4409-9a51-600cf115ff4a",
    traceEventsPath: "/v1/query/4576b626-c27a-4409-9a51-600cf115ff4a/events",
    route: "rag",
    correctedQuery: null,
    evidenceStatus: "sufficient",
    abstained: false,
    claims: [
      {
        claimId: "claim-1",
        text: "Raw query content is retained for 30 days.",
        confidence: 0.99,
        citationIds: ["C1"],
        supportStatus: "supported",
      },
    ],
    citations: [
      {
        citationId: "C1",
        documentTitle: "Cortex Retention Standard",
        documentVersion: "1.4",
        chunkId: "chunk-1",
        structuralLocator: "section:retention",
        exactSpan: "Raw query content is retained for 30 days.",
        supportScore: 0.99,
      },
    ],
    stages: [],
  },
};

const abstainedQueryResponse = {
  ...queryResponse,
  choices: [
    {
      index: 0,
      message: {
        role: "assistant",
        content: "I do not have enough consistent evidence to answer that safely.",
      },
      finish_reason: "stop",
    },
  ],
  x_cortex: {
    ...queryResponse.x_cortex,
    evidenceStatus: "conflict",
    abstained: true,
    claims: [
      {
        claimId: "claim-1",
        text: "Retention differs between two policy sources.",
        confidence: 0.41,
        citationIds: ["C1"],
        supportStatus: "conflict",
      },
    ],
  },
};

function mockSuccessfulQuery(): void {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(sessionResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(contractResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(queryResponse), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-Cortex-Contract-Version": "v1",
            "X-Cortex-Trace-Id": "4576b626-c27a-4409-9a51-600cf115ff4a",
            "X-Cortex-Evidence-Status": "sufficient",
            "X-Cortex-Route": "rag",
            "X-Cortex-Abstained": "false",
          },
        }),
      ),
  );
}

function mockSessionOnly(): void {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(sessionResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(contractResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
  );
}

function mockAbstainedQuery(): void {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(sessionResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(contractResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(abstainedQueryResponse), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-Cortex-Contract-Version": "v1",
            "X-Cortex-Trace-Id": "4576b626-c27a-4409-9a51-600cf115ff4a",
            "X-Cortex-Evidence-Status": "conflict",
            "X-Cortex-Route": "rag",
            "X-Cortex-Abstained": "true",
          },
        }),
      ),
  );
}

function mockIncompatibleContract(): void {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(sessionResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...contractResponse,
            employeeSafeExtensionFields: ["contractVersion", "traceId"],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
  );
}

function mockSemanticallyIncompatibleContract(): void {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(sessionResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...contractResponse,
            responseHeaders: ["X-Cortex-Contract-Version", "X-Cortex-Trace-Id"],
            errorStatuses: contractResponse.errorStatuses.filter(
              (errorStatus) => errorStatus.code !== "provider_unavailable",
            ),
            abstentionEvidenceStatuses: ["insufficient"],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EndUserQuery", () => {
  it("keeps pipeline internals out of the employee welcome surface", async () => {
    mockSessionOnly();
    render(<EndUserQuery />);

    expect(
      await screen.findByRole("heading", { name: "What would you like to know?" }),
    ).toBeVisible();
    expect(screen.queryByText("Cross-Encoder")).not.toBeInTheDocument();
    expect(screen.queryByText("Pipeline")).not.toBeInTheDocument();
  });

  it("submits an authenticated query and displays validated citations", async () => {
    mockSuccessfulQuery();
    render(<EndUserQuery />);
    expect(
      await screen.findByText("Your access permissions are applied automatically."),
    ).toBeVisible();

    fireEvent.change(screen.getByRole("textbox", { name: "Ask a question" }), {
      target: { value: "What are our data retention rules?" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Submit question" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit question" }));

    expect(await screen.findByRole("heading", { name: "Answer" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Sources" })).toBeVisible();
    expect(screen.getByText("Cortex Retention Standard")).toBeVisible();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  });

  it("hides citation presentation without changing query execution", async () => {
    mockSuccessfulQuery();
    render(<EndUserQuery />);
    expect(
      await screen.findByText("Your access permissions are applied automatically."),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("checkbox", { name: "Show citations" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ask a question" }), {
      target: { value: "What are our data retention rules?" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Submit question" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit question" }));

    expect(await screen.findByRole("heading", { name: "Answer" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("surfaces abstention and conflicting evidence honestly", async () => {
    mockAbstainedQuery();
    render(<EndUserQuery />);
    expect(
      await screen.findByText("Your access permissions are applied automatically."),
    ).toBeVisible();

    fireEvent.change(screen.getByRole("textbox", { name: "Ask a question" }), {
      target: { value: "What is the retention period?" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Submit question" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Submit question" }));

    expect(await screen.findByRole("heading", { name: "Conflicting evidence" })).toBeVisible();
    expect(screen.getByText("Conflicting authorized evidence detected")).toBeVisible();
    expect(
      screen.getByText(/withheld a fully supported answer/i),
    ).toBeVisible();
  });

  it("fails safely when the deployed package advertises an incompatible query contract", async () => {
    mockIncompatibleContract();
    render(<EndUserQuery />);

    expect(await screen.findByText(/incompatible with the deployed package/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Submit question" })).toBeDisabled();
  });

  it("fails safely when the deployed package drifts from the expected evidence and error contract", async () => {
    mockSemanticallyIncompatibleContract();
    render(<EndUserQuery />);

    expect(await screen.findByText(/incompatible with the deployed package/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Submit question" })).toBeDisabled();
  });
});
