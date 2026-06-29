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
  it("surfaces stale running locks and retry pressure as operator actions", async () => {
    const currentTime = Date.now();
    const lockedAtIso = new Date(currentTime - (25 * 60 * 1000)).toISOString();
    const availableAtIso = new Date(currentTime - (30 * 60 * 1000)).toISOString();

    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              jobId: "50000000-0000-0000-0000-000000000010",
              jobType: "ingestion.source",
              status: "running",
              attempts: 3,
              updatedAt: lockedAtIso,
              lastError: "Docling timed out twice before this retry.",
              documentId: "30000000-0000-0000-0000-000000000010",
              sourceDisplayName: "Policy Rollup",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            jobId: "50000000-0000-0000-0000-000000000010",
            enterpriseId: "00000000-0000-0000-0000-000000000001",
            jobType: "ingestion.source",
            status: "running",
            attempts: 3,
            availableAt: availableAtIso,
            lockedAt: lockedAtIso,
            lastError: "Docling timed out twice before this retry.",
            documentId: "30000000-0000-0000-0000-000000000010",
            documentVersionId: "40000000-0000-0000-0000-000000000010",
            sourceDisplayName: "Policy Rollup",
            updatedAt: lockedAtIso,
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

    expect(await screen.findByText("Policy Rollup")).toBeVisible();
    expect(await screen.findByText("Job operator queue")).toBeVisible();
    expect(screen.getByText("Investigate stale running job")).toBeVisible();
    expect(screen.getByText("Review retry pressure")).toBeVisible();
    expect(screen.getByText("Locked for 25m. Check worker health, startup gate, and the source diagnostics before retrying.")).toBeVisible();
    expect(screen.getByText("3 attempts with last error: Docling timed out twice before this retry.. Repair the root cause before more retries.")).toBeVisible();
    expect(screen.getByText("Lock age")).toBeVisible();
    expect(screen.getByText("25m")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

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
