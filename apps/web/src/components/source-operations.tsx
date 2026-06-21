/** Live source onboarding workspace for developer-side uploads, websites, and version inspection. */

import { type ChangeEvent, type FormEvent, useEffect, useMemo, useState } from "react";
import {
  CheckCircle,
  Clock,
  Database,
  GlobeHemisphereWest,
  UploadSimple,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  createUploadSource,
  createWebsiteSource,
  getSourceDetail,
  getSources,
} from "../lib/api-client";
import type { SourceDetail, SourceSummary } from "../types";

interface SourceOperationsProps {
  enterpriseId: string;
  onJobQueued: (jobId: string) => void;
}

/** Render the developer source inventory, onboarding forms, and version diagnostics. */
export function SourceOperations({ enterpriseId, onJobQueued }: SourceOperationsProps) {
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<SourceDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [uploadForm, setUploadForm] = useState({
    displayName: "",
    principalIds: "group:employees",
    versionLabel: "1.0",
  });
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [websiteForm, setWebsiteForm] = useState({
    displayName: "",
    principalIds: "group:employees",
    sourceUri: "http://127.0.0.1:8765",
    versionLabel: "1.0",
  });

  useEffect(() => {
    let isMounted = true;

    async function loadSources(): Promise<void> {
      try {
        const sourceSummaries = await getSources(enterpriseId);
        if (!isMounted) {
          return;
        }
        setSources(sourceSummaries);
        if (!selectedDocumentId && sourceSummaries.length > 0) {
          setSelectedDocumentId(sourceSummaries[0].documentId);
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error instanceof Error ? error.message : "Failed to load sources");
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    void loadSources();
    const pollTimer = window.setInterval(() => {
      void loadSources();
    }, 5000);
    return () => {
      isMounted = false;
      window.clearInterval(pollTimer);
    };
  }, [enterpriseId]);

  useEffect(() => {
    let isMounted = true;
    if (!selectedDocumentId) {
      setSelectedSource(null);
      return;
    }

    async function loadDetail(): Promise<void> {
      try {
        const detail = await getSourceDetail(enterpriseId, selectedDocumentId as string);
        if (isMounted) {
          setSelectedSource(detail);
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error instanceof Error ? error.message : "Failed to load source detail");
        }
      }
    }

    void loadDetail();
    return () => {
      isMounted = false;
    };
  }, [enterpriseId, selectedDocumentId]);

  const latestVersion = useMemo(
    () => selectedSource?.versions[0] ?? null,
    [selectedSource],
  );

  async function handleUploadSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!uploadFile || isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const response = await createUploadSource({
        displayName: uploadForm.displayName || uploadFile.name,
        enterpriseId,
        file: uploadFile,
        principalIds: parsePrincipalIds(uploadForm.principalIds),
        versionLabel: uploadForm.versionLabel,
      });
      setSelectedDocumentId(response.documentId);
      setUploadFile(null);
      setUploadForm((currentForm) => ({ ...currentForm, displayName: "" }));
      setSuccessMessage(`Queued upload ${response.jobId.slice(0, 8)} for processing.`);
      onJobQueued(response.jobId);
      setSources(await getSources(enterpriseId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleWebsiteSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const response = await createWebsiteSource({
        displayName: websiteForm.displayName,
        enterpriseId,
        extractionQuality: 0.9,
        principalIds: parsePrincipalIds(websiteForm.principalIds),
        sourceUri: websiteForm.sourceUri,
        sourceAuthority: 0.85,
        versionLabel: websiteForm.versionLabel,
      });
      setSelectedDocumentId(response.documentId);
      setSuccessMessage(`Queued website ${response.jobId.slice(0, 8)} for processing.`);
      onJobQueued(response.jobId);
      setSources(await getSources(enterpriseId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Website ingestion failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleUploadFileChange(event: ChangeEvent<HTMLInputElement>): void {
    setUploadFile(event.target.files?.[0] ?? null);
  }

  return (
    <section className="source-operations">
      <div className="source-forms">
        <form className="source-form-card" onSubmit={handleUploadSubmit}>
          <div className="source-form-card__heading">
            <UploadSimple aria-hidden size={18} />
            <strong>Upload source</strong>
          </div>
          <label>
            Display name
            <input
              value={uploadForm.displayName}
              onChange={(event) =>
                setUploadForm((currentForm) => ({
                  ...currentForm,
                  displayName: event.target.value,
                }))
              }
              placeholder="Quarterly policy packet"
            />
          </label>
          <label>
            Version
            <input
              value={uploadForm.versionLabel}
              onChange={(event) =>
                setUploadForm((currentForm) => ({
                  ...currentForm,
                  versionLabel: event.target.value,
                }))
              }
            />
          </label>
          <label>
            ACL principals
            <input
              value={uploadForm.principalIds}
              onChange={(event) =>
                setUploadForm((currentForm) => ({
                  ...currentForm,
                  principalIds: event.target.value,
                }))
              }
            />
          </label>
          <label>
            File
            <input type="file" onChange={handleUploadFileChange} />
          </label>
          <button className="button button--primary" type="submit" disabled={!uploadFile || isSubmitting}>
            Queue upload
          </button>
        </form>

        <form className="source-form-card" onSubmit={handleWebsiteSubmit}>
          <div className="source-form-card__heading">
            <GlobeHemisphereWest aria-hidden size={18} />
            <strong>Add website</strong>
          </div>
          <label>
            Display name
            <input
              value={websiteForm.displayName}
              onChange={(event) =>
                setWebsiteForm((currentForm) => ({
                  ...currentForm,
                  displayName: event.target.value,
                }))
              }
              placeholder="Support handbook"
            />
          </label>
          <label>
            Source URL
            <input
              value={websiteForm.sourceUri}
              onChange={(event) =>
                setWebsiteForm((currentForm) => ({
                  ...currentForm,
                  sourceUri: event.target.value,
                }))
              }
            />
          </label>
          <label>
            Version
            <input
              value={websiteForm.versionLabel}
              onChange={(event) =>
                setWebsiteForm((currentForm) => ({
                  ...currentForm,
                  versionLabel: event.target.value,
                }))
              }
            />
          </label>
          <label>
            ACL principals
            <input
              value={websiteForm.principalIds}
              onChange={(event) =>
                setWebsiteForm((currentForm) => ({
                  ...currentForm,
                  principalIds: event.target.value,
                }))
              }
            />
          </label>
          <button className="button button--secondary" type="submit" disabled={isSubmitting}>
            Queue website
          </button>
        </form>
      </div>

      {errorMessage ? (
        <div className="query-error" role="alert">
          <WarningCircle aria-hidden size={18} />
          <div>
            <strong>Source operations warning</strong>
            <span>{errorMessage}</span>
          </div>
        </div>
      ) : null}
      {successMessage ? (
        <div className="source-success">
          <CheckCircle aria-hidden size={18} weight="fill" />
          <span>{successMessage}</span>
        </div>
      ) : null}

      <div className="source-operations__workspace">
        <section className="source-list-card" aria-label="Sources">
          <div className="section-heading">
            <Database aria-hidden size={18} />
            <strong>Sources</strong>
            <span>{sources.length}</span>
          </div>
          {isLoading ? (
            <div className="empty-tab">
              <Clock aria-hidden size={24} />
              <p>Loading live sources…</p>
            </div>
          ) : sources.length === 0 ? (
            <div className="empty-tab">
              <Database aria-hidden size={24} />
              <p>No sources yet. Upload a file or add an allowlisted page.</p>
            </div>
          ) : (
            <div className="source-list">
              {sources.map((source) => (
                <button
                  key={source.documentId}
                  className={`source-list__item${
                    selectedDocumentId === source.documentId ? " is-active" : ""
                  }`}
                  type="button"
                  onClick={() => setSelectedDocumentId(source.documentId)}
                >
                  <div>
                    <strong>{source.displayName}</strong>
                    <span>{source.sourceType} · {source.latestVersionLabel ?? "Pending"}</span>
                    <small>
                      {source.latestIngestionStatus ?? "queued"} · quarantine{" "}
                      {source.latestQuarantineStatus ?? "unknown"} · malware{" "}
                      {source.latestMalwareStatus ?? "unknown"}
                    </small>
                  </div>
                  <small>{source.latestIngestionStatus ?? "queued"}</small>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="source-detail-card" aria-label="Source detail">
          <div className="section-heading">
            <CheckCircle aria-hidden size={18} />
            <strong>{selectedSource?.displayName ?? "Source detail"}</strong>
            <span>{selectedSource?.sourceType ?? "waiting"}</span>
          </div>
          {selectedSource && latestVersion ? (
            <div className="source-detail">
              <div className="source-detail__hero">
                <div>
                  <span className="status-badge"><span /> {latestVersion.ingestionStatus}</span>
                  <h2>{selectedSource.displayName}</h2>
                  <p>{selectedSource.sourceUri}</p>
                </div>
                <dl className="source-detail__facts">
                  <div><dt>ACLs</dt><dd>{latestVersion.principalIds.join(", ")}</dd></div>
                  <div><dt>Activation</dt><dd>{latestVersion.activatedAt ? new Date(latestVersion.activatedAt).toLocaleString() : "inactive"}</dd></div>
                  <div><dt>Malware</dt><dd>{latestVersion.malwareStatus}</dd></div>
                  <div><dt>Quarantine</dt><dd>{latestVersion.quarantineStatus}</dd></div>
                  <div><dt>Parser</dt><dd>{latestVersion.parserName} · {latestVersion.parserVersion}</dd></div>
                  <div><dt>Accelerators</dt><dd>{latestVersion.acceleratorReports.length || 0}</dd></div>
                </dl>
              </div>
              <div className="source-detail__versions">
                <h3>Version history</h3>
                {latestVersion.failureDetail ? (
                  <div className="query-error" role="alert" style={{ marginBottom: 12 }}>
                    <WarningCircle aria-hidden size={18} />
                    <div>
                      <strong>Latest failure detail</strong>
                      <span>{latestVersion.failureDetail}</span>
                    </div>
                  </div>
                ) : null}
                <table>
                  <thead>
                    <tr>
                      <th>Version</th>
                      <th>Status</th>
                      <th>MIME</th>
                      <th>Raw SHA-256</th>
                      <th>Failure</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedSource.versions.map((version) => (
                      <tr key={version.documentVersionId}>
                        <td>{version.versionLabel}</td>
                        <td>{version.ingestionStatus}</td>
                        <td>{version.mimeType ?? "unknown"}</td>
                        <td><code>{version.rawSha256.slice(0, 16)}</code></td>
                        <td>{version.failureCode ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="empty-tab">
              <Clock aria-hidden size={24} />
              <p>Select a source to inspect its live version history and diagnostics.</p>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function parsePrincipalIds(rawPrincipalIds: string): string[] {
  return rawPrincipalIds
    .split(",")
    .map((principalId) => principalId.trim())
    .filter((principalId) => principalId.length > 0);
}
