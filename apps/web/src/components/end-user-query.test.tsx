/** Employee query tests protect the simple UI and citation-display boundary. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EndUserQuery } from "./end-user-query";

const queryResponse = {
  traceId: "4576b626-c27a-4409-9a51-600cf115ff4a",
  route: "rag",
  correctedQuery: null,
  answer: "Raw query content is retained for 30 days.",
  evidenceStatus: "sufficient",
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
};

function mockSuccessfulQuery(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(queryResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EndUserQuery", () => {
  it("keeps pipeline internals out of the employee welcome surface", () => {
    render(<EndUserQuery />);

    expect(screen.getByRole("heading", { name: "What would you like to know?" })).toBeVisible();
    expect(screen.queryByText("Cross-Encoder")).not.toBeInTheDocument();
    expect(screen.queryByText("Pipeline")).not.toBeInTheDocument();
  });

  it("submits a scoped query and displays validated citations", async () => {
    mockSuccessfulQuery();
    render(<EndUserQuery />);

    fireEvent.change(screen.getByRole("textbox", { name: "Ask a question" }), {
      target: { value: "What are our data retention rules?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit question" }));

    expect(await screen.findByRole("heading", { name: "Answer" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Sources" })).toBeVisible();
    expect(screen.getByText("Cortex Retention Standard")).toBeVisible();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  });

  it("hides citation presentation without changing query execution", async () => {
    mockSuccessfulQuery();
    render(<EndUserQuery />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Show citations" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ask a question" }), {
      target: { value: "What are our data retention rules?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit question" }));

    expect(await screen.findByRole("heading", { name: "Answer" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
  });
});
