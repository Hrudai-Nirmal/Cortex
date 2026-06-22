/** Source operations tests cover live source inventory and version-detail visibility. */

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SourceOperations } from "./source-operations";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("SourceOperations", () => {
  it("loads the source list and selected version history", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              documentId: "30000000-0000-0000-0000-000000000001",
              displayName: "Retention Packet",
              sourceType: "upload",
              sourceUri: "upload://retention-packet.pdf",
              createdBy: "alex.rivera@example.com",
              updatedAt: "2026-06-21T00:00:00+00:00",
              latestVersionLabel: "1.2",
              latestIngestionStatus: "active",
              latestQuarantineStatus: "clear",
              latestMalwareStatus: "clean",
              latestPublishedAt: "2026-06-20T00:00:00+00:00",
              latestActivatedAt: "2026-06-21T00:00:00+00:00",
              principalIds: ["group:employees"],
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            documentId: "30000000-0000-0000-0000-000000000001",
            displayName: "Retention Packet",
            sourceType: "upload",
            sourceUri: "upload://retention-packet.pdf",
            createdBy: "alex.rivera@example.com",
            updatedAt: "2026-06-21T00:00:00+00:00",
            versions: [
              {
                documentVersionId: "40000000-0000-0000-0000-000000000001",
                versionLabel: "1.2",
                status: "active",
                ingestionStatus: "active",
                quarantineStatus: "clear",
                malwareStatus: "clean",
                mimeType: "application/pdf",
                parserName: "docling",
                parserVersion: "2.x-pinned-at-install",
                objectKey: "blobs/sha256/abc.pdf",
                rawSha256: "a".repeat(64),
                canonicalContentSha256: "b".repeat(64),
                sourceAuthority: 0.95,
                publishedAt: "2026-06-20T00:00:00+00:00",
                createdAt: "2026-06-21T00:00:00+00:00",
                activatedAt: "2026-06-21T00:00:00+00:00",
                failureCode: null,
                failureDetail: null,
                extractionDiagnostics: { pageCount: 12 },
                acceleratorReports: [{ actualDevice: "mps", stageName: "docling-layout-table-ocr" }],
                principalIds: ["group:employees"],
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(
      <SourceOperations
        enterpriseId="00000000-0000-0000-0000-000000000001"
        onJobQueued={() => undefined}
      />,
    );

    expect(await screen.findByText("Retention Packet")).toBeVisible();
    expect(screen.getAllByText("Active").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Processing")).toBeVisible();
    expect(await screen.findByText(/2.x-pinned-at-install/)).toBeVisible();
    expect(screen.getByText(/quarantine clear/i)).toBeVisible();
    expect(screen.getByText("Latest version diagnostics")).toBeVisible();
    expect(screen.getByText("Latest active")).toBeVisible();
    expect(screen.getAllByText("ACL principals").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("alex.rivera@example.com")).toBeVisible();
    expect(screen.getByText(/Extraction diagnostics/)).toBeVisible();
    expect(screen.getByText(/12/)).toBeVisible();
    expect(screen.getByText(/Accelerator reports/)).toBeVisible();
    expect(screen.getByText(/mps/)).toBeVisible();
    expect(screen.getByRole("region", { name: "Source detail" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
