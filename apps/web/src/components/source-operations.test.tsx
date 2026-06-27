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
            sourceFingerprint: "c".repeat(64),
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
    expect(screen.getByText("Retrieval status")).toBeVisible();
    expect(screen.getByText("Retrievable now")).toBeVisible();
    expect(screen.getByText("Source fingerprint")).toBeVisible();
    expect(screen.getByText("c".repeat(64))).toBeVisible();
    expect(screen.getAllByText("ACL principals").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("alex.rivera@example.com")).toBeVisible();
    expect(screen.getByText(/Extraction diagnostics/)).toBeVisible();
    expect(screen.getByText(/12/)).toBeVisible();
    expect(screen.getByText(/Accelerator reports/)).toBeVisible();
    expect(screen.getByText(/mps/)).toBeVisible();
    expect(await screen.findByText("Operator queue")).toBeVisible();
    expect(screen.getByText("No source onboarding actions are blocking retrieval right now.")).toBeVisible();
    expect(screen.getByRole("region", { name: "Source detail" })).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("shows when the newest version is not retrievable and an older active version still serves queries", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              documentId: "30000000-0000-0000-0000-000000000001",
              displayName: "Security Handbook",
              sourceType: "upload",
              sourceUri: "upload://security-handbook.pdf",
              createdBy: "maya.chen@example.com",
              updatedAt: "2026-06-21T00:00:00+00:00",
              latestVersionLabel: "2.0",
              latestIngestionStatus: "failed",
              latestQuarantineStatus: "clear",
              latestMalwareStatus: "clean",
              latestPublishedAt: "2026-06-20T00:00:00+00:00",
              latestActivatedAt: "2026-06-19T00:00:00+00:00",
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
            displayName: "Security Handbook",
            sourceType: "upload",
            sourceUri: "upload://security-handbook.pdf",
            createdBy: "maya.chen@example.com",
            updatedAt: "2026-06-21T00:00:00+00:00",
            sourceFingerprint: "d".repeat(64),
            versions: [
              {
                documentVersionId: "40000000-0000-0000-0000-000000000002",
                versionLabel: "2.0",
                status: "failed",
                ingestionStatus: "failed",
                quarantineStatus: "clear",
                malwareStatus: "clean",
                mimeType: "application/pdf",
                parserName: "docling",
                parserVersion: "2.x-pinned-at-install",
                objectKey: "blobs/sha256/fail.pdf",
                rawSha256: "e".repeat(64),
                canonicalContentSha256: "f".repeat(64),
                sourceAuthority: 0.91,
                publishedAt: "2026-06-20T00:00:00+00:00",
                createdAt: "2026-06-21T00:00:00+00:00",
                activatedAt: null,
                failureCode: "SOURCE_PARSE_FAILED",
                failureDetail: "Docling could not parse page structure.",
                extractionDiagnostics: { pageCount: 30 },
                acceleratorReports: [],
                principalIds: ["group:employees"],
              },
              {
                documentVersionId: "40000000-0000-0000-0000-000000000001",
                versionLabel: "1.9",
                status: "active",
                ingestionStatus: "active",
                quarantineStatus: "clear",
                malwareStatus: "clean",
                mimeType: "application/pdf",
                parserName: "docling",
                parserVersion: "2.x-pinned-at-install",
                objectKey: "blobs/sha256/active.pdf",
                rawSha256: "a".repeat(64),
                canonicalContentSha256: "b".repeat(64),
                sourceAuthority: 0.95,
                publishedAt: "2026-06-19T00:00:00+00:00",
                createdAt: "2026-06-19T00:00:00+00:00",
                activatedAt: "2026-06-19T00:00:00+00:00",
                failureCode: null,
                failureDetail: null,
                extractionDiagnostics: { pageCount: 28 },
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

    expect(await screen.findByText("Security Handbook")).toBeVisible();
    expect(await screen.findByText("Latest version is not retrievable")).toBeVisible();
    expect(screen.getByText(/version 2.0 is failed/i)).toBeVisible();
    expect(screen.getByText(/active version 1.9 remains the live retrieval candidate/i)).toBeVisible();
    expect(screen.getByText("Retrievable active version")).toBeVisible();
    expect(screen.getAllByText("Not retrievable").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Operator queue")).toBeVisible();
    expect(screen.getByText(/Sources need retry or quarantine review before the latest versions can be trusted./i)).toBeVisible();
    expect(screen.getByText(/Security Handbook latest version 2.0 is not retrievable, so Cortex still serves 1.9 until onboarding is repaired./i)).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
