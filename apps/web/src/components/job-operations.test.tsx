/** Job operations tests keep durable failure visibility present for developers. */

import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobOperations } from "./job-operations";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("JobOperations", () => {
  it("shows failed durable jobs with their last error", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              jobId: "50000000-0000-0000-0000-000000000001",
              jobType: "ingestion.source",
              status: "failed",
              attempts: 1,
              updatedAt: "2026-06-21T00:00:00+00:00",
              lastError: "Docling failed to parse source.pdf",
              documentId: "30000000-0000-0000-0000-000000000001",
              sourceDisplayName: "Retention Packet",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            jobId: "50000000-0000-0000-0000-000000000001",
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            jobType: "ingestion.source",
            status: "failed",
            attempts: 1,
            availableAt: "2026-06-21T00:00:00+00:00",
            lockedAt: "2026-06-21T00:01:00+00:00",
            lastError: "Docling failed to parse source.pdf",
            documentId: "30000000-0000-0000-0000-000000000001",
            documentVersionId: "40000000-0000-0000-0000-000000000001",
            sourceDisplayName: "Retention Packet",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(
      <JobOperations
        enterpriseId="00000000-0000-0000-0000-000000000001"
        highlightedJobId={null}
      />,
    );

    expect(await screen.findByText("Retention Packet")).toBeVisible();
    expect(screen.getByText("Operator attention")).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Attempts" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "Updated" })).toBeVisible();
    expect(await screen.findByText("Selected job detail")).toBeVisible();
    expect(screen.getAllByText("Docling failed to parse source.pdf").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("40000000-0000-0000-0000-000000000001")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("refreshes selected job detail while the list keeps polling", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              jobId: "50000000-0000-0000-0000-000000000001",
              jobType: "ingestion.source",
              status: "running",
              attempts: 1,
              updatedAt: "2026-06-21T00:00:00+00:00",
              lastError: null,
              documentId: "30000000-0000-0000-0000-000000000001",
              sourceDisplayName: "Retention Packet",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            jobId: "50000000-0000-0000-0000-000000000001",
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            jobType: "ingestion.source",
            status: "running",
            attempts: 1,
            availableAt: "2026-06-21T00:00:00+00:00",
            lockedAt: "2026-06-21T00:01:00+00:00",
            lastError: null,
            documentId: "30000000-0000-0000-0000-000000000001",
            documentVersionId: "40000000-0000-0000-0000-000000000001",
            sourceDisplayName: "Retention Packet",
            updatedAt: "2026-06-21T00:01:00+00:00",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              jobId: "50000000-0000-0000-0000-000000000001",
              jobType: "ingestion.source",
              status: "failed",
              attempts: 2,
              updatedAt: "2026-06-21T00:04:00+00:00",
              lastError: "Docling timed out",
              documentId: "30000000-0000-0000-0000-000000000001",
              sourceDisplayName: "Retention Packet",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            jobId: "50000000-0000-0000-0000-000000000001",
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            jobType: "ingestion.source",
            status: "failed",
            attempts: 2,
            availableAt: "2026-06-21T00:00:00+00:00",
            lockedAt: "2026-06-21T00:04:00+00:00",
            lastError: "Docling timed out",
            documentId: "30000000-0000-0000-0000-000000000001",
            documentVersionId: "40000000-0000-0000-0000-000000000001",
            sourceDisplayName: "Retention Packet",
            updatedAt: "2026-06-21T00:04:00+00:00",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(
      <JobOperations
        enterpriseId="00000000-0000-0000-0000-000000000001"
        highlightedJobId={null}
      />,
    );

    expect(await screen.findByText("Retention Packet")).toBeVisible();
    expect(screen.getAllByText("running").length).toBeGreaterThanOrEqual(1);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 4100));
    });

    await waitFor(() =>
      expect(screen.getAllByText("Docling timed out").length).toBeGreaterThanOrEqual(1),
    );
    expect(screen.getAllByText("failed").length).toBeGreaterThanOrEqual(1);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  }, 12000);
});
