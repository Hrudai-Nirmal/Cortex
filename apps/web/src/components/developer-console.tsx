/** Graph-first developer console faithful to the selected Signal Grid mockup. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CaretDown,
  CheckCircle,
  Clock,
  FloppyDisk,
  Play,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  activatePipeline,
  getExternalQueryContract,
  getActivePipeline,
  getLatestTrace,
  getPipelineVersions,
  getRuntimeHealth,
  getStartupHealth,
  getSession,
  subscribeToTraceEvents,
  validatePipeline,
} from "../lib/api-client";
import { getConsolePublicUrl, getQueryPublicUrl } from "../config";
import type {
  ExternalQueryContractDescriptor,
  PipelineGraph,
  PipelineVersionSummary,
  QueryStageEvent,
  RuntimeHealth,
  Session,
  TraceSummary,
} from "../types";
import { JobOperations } from "./job-operations";
import { PipelineGraph as PipelineGraphCanvas } from "./pipeline-graph";
import { SourceOperations } from "./source-operations";

const ENTERPRISE_ID = "00000000-0000-0000-0000-000000000001";
const EXTERNAL_QUERY_CONTRACT_VERSION = "v1";
const EXTERNAL_QUERY_HEADER_NAMES = [
  "X-Cortex-Contract-Version",
  "X-Cortex-Trace-Id",
  "X-Cortex-Evidence-Status",
  "X-Cortex-Route",
  "X-Cortex-Abstained",
] as const;

const inspectorContent: Record<string, { title: string; type: string; detail: string }> = {
  ingest: { title: "Ingest & Normalize", type: "Ingestion", detail: "Docling parser, deterministic chunking, metadata, versions" },
  scope: { title: "Access Scope", type: "Security invariant", detail: "Enterprise and ACL principals enforced inside retrieval SQL" },
  retrieval: { title: "Hybrid Retrieval", type: "Retrieval", detail: "PostgreSQL full text + pgvector cosine search" },
  rerank: { title: "Cross-Encoder", type: "Reranking", detail: "RRF candidates truncated before local cross-encoder scoring" },
  confidence: { title: "Source Confidence", type: "Evidence scoring", detail: "Authority, freshness, extraction quality, corroboration" },
  generation: { title: "Bounded Generation", type: "Generation", detail: "Schema-constrained atomic claims with no dynamic tools" },
  citations: { title: "Claims & Citations", type: "Validation", detail: "Every supported claim maps to an exact versioned source span" },
  bm25: { title: "BM25 Index", type: "Lexical index", detail: "PostgreSQL full-text ranking under the mandatory access predicate" },
  vector: { title: "Vector Index", type: "Vector index", detail: "Filtered HNSW search with iterative-scan recall monitoring" },
  "reranker-model": { title: "Reranker Model", type: "Model provider", detail: "Pinned local cross-encoder applied to no more than 40 candidates" },
  abstain: { title: "Insufficient Evidence", type: "Answer policy", detail: "Return no answer when no independently supported claim passes its gate" },
};

interface SurfaceDeploymentCheck {
  label: string;
  status: "ready" | "degraded";
  detail: string;
  remediation: string;
}

function findRuntimeComponent(
  runtimeHealth: RuntimeHealth | null,
  componentName: string,
) {
  return runtimeHealth?.components.find((component) => component.name === componentName) ?? null;
}

function getUrlOrigin(urlValue: string): string | null {
  try {
    return new URL(urlValue).origin;
  } catch {
    return null;
  }
}

function isRootUrl(urlValue: string): boolean {
  try {
    const resolvedUrl = new URL(urlValue);
    return resolvedUrl.pathname === "/" || resolvedUrl.pathname === "";
  } catch {
    return false;
  }
}

function parseDeploymentConfig(
  detail: string | undefined,
): { consoleUrl: string | null; queryUrl: string | null; startupPolicy: string | null } {
  if (!detail) {
    return { consoleUrl: null, queryUrl: null, startupPolicy: null };
  }
  const consoleMatch = detail.match(/console=([^,]+), query=/);
  const queryMatch = detail.match(/query=([^,]+), cors=/);
  const startupPolicyMatch = detail.match(/startupPolicy=([^,]+)/);
  return {
    consoleUrl: consoleMatch?.[1] ?? null,
    queryUrl: queryMatch?.[1] ?? null,
    startupPolicy: startupPolicyMatch?.[1] ?? null,
  };
}

function buildSurfaceDeploymentChecks(
  environment: string | undefined,
  consoleUrl: string,
  queryUrl: string,
  startupPolicy: string | null,
  queryContract: ExternalQueryContractDescriptor | null,
): SurfaceDeploymentCheck[] {
  const consoleOrigin = getUrlOrigin(consoleUrl);
  const queryOrigin = getUrlOrigin(queryUrl);
  const hasDistinctOrigins =
    Boolean(consoleOrigin) && Boolean(queryOrigin) && consoleOrigin !== queryOrigin;
  const hasRootHosts = isRootUrl(consoleUrl) && isRootUrl(queryUrl);
  const requiresFailClosed = environment === "production";

  return [
    {
      label: "Browser host split",
      status: hasDistinctOrigins && hasRootHosts ? "ready" : "degraded",
      detail: hasDistinctOrigins
        ? `Console ${consoleOrigin} and query ${queryOrigin} stay isolated as separate browser origins.`
        : "Console and query surfaces are not isolated on distinct browser origins.",
      remediation: hasDistinctOrigins && hasRootHosts
        ? "Keep both browser surfaces routed at host roots so client DNS and ingress rules remain unambiguous."
        : "Configure distinct root-host public URLs for the console and query images before shipping the client package.",
    },
    {
      label: "Startup policy",
      status:
        !requiresFailClosed || startupPolicy === "fail-closed" ? "ready" : "degraded",
      detail: startupPolicy
        ? `Deployment startup policy is ${startupPolicy}.`
        : "Deployment startup policy is not visible in runtime health.",
      remediation:
        !requiresFailClosed || startupPolicy === "fail-closed"
          ? "Keep fail-closed startup enabled for packaged production rollouts and report-only for local development profiles."
          : "Production packages must expose startupPolicy=fail-closed so degraded runtime dependencies stop boot instead of serving partial state.",
    },
    {
      label: "Query contract handshake",
      status: queryContract ? "ready" : "degraded",
      detail: queryContract
        ? `Contract ${queryContract.contractVersion} advertises ${queryContract.method} ${queryContract.endpointPath} with ${queryContract.authentication} authentication.`
        : "The live replacement-query contract descriptor is unavailable.",
      remediation: queryContract
        ? "Replacement chat shells should validate the live contract descriptor before trusting the deployed query surface."
        : "Restore GET /v1/chat/contracts/v1 so bundled and client-owned query UIs can verify the live Cortex contract before sending traffic.",
    },
  ];
}

function buildLoadWarnings(loadFailures: string[]): string | null {
  if (loadFailures.length === 0) {
    return null;
  }
  return `Some operator data is unavailable: ${loadFailures.join(" | ")}`;
}

function getNonReadyComponents(runtimeHealth: RuntimeHealth | null) {
  return runtimeHealth?.components.filter((component) => component.status !== "ready") ?? [];
}

/** Render pipeline editing, inspection, publishing, and trace controls for builders. */
export function DeveloperConsole() {
  const [selectedNodeId, setSelectedNodeId] = useState("rerank");
  const [activeTab, setActiveTab] = useState("Graph");
  const [publishState, setPublishState] = useState<"saved" | "validating" | "publishing" | "published">("saved");
  const [pipeline, setPipeline] = useState<PipelineGraph | null>(null);
  const [pipelineVersions, setPipelineVersions] = useState<PipelineVersionSummary[]>([]);
  const [startupHealth, setStartupHealth] = useState<RuntimeHealth | null>(null);
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(null);
  const [latestTrace, setLatestTrace] = useState<TraceSummary | null>(null);
  const [queryContract, setQueryContract] = useState<ExternalQueryContractDescriptor | null>(
    null,
  );
  const [session, setSession] = useState<Session | null>(null);
  const [tracePlayback, setTracePlayback] = useState<QueryStageEvent[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [highlightedJobId, setHighlightedJobId] = useState<string | null>(null);
  const traceSubscriptionRef = useRef<(() => void) | null>(null);
  const selectedInspector = useMemo(() => inspectorContent[selectedNodeId], [selectedNodeId]);
  const displayedEvents = tracePlayback.length > 0 ? tracePlayback : latestTrace?.stageEvents ?? [];
  const startupAlerts = getNonReadyComponents(startupHealth);
  const runtimeAlerts = getNonReadyComponents(runtimeHealth);
  const modelProfile = findRuntimeComponent(runtimeHealth, "model-profile");
  const packageBuildProfile = findRuntimeComponent(runtimeHealth, "package-build-profile");
  const identityProfile = findRuntimeComponent(runtimeHealth, "identity-profile");
  const deploymentConfig =
    findRuntimeComponent(startupHealth, "deployment-config")
    ?? findRuntimeComponent(runtimeHealth, "deployment-config");
  const validatedVersions = pipelineVersions.filter((version) => version.status === "validated");
  const rollbackCandidates = pipelineVersions.filter((version) => version.status === "retired");
  const activeVersion = pipelineVersions.find((version) => version.status === "active") ?? null;

  const loadConsole = useCallback(async (): Promise<void> => {
    try {
      const [
        activePipelineResult,
        versionsResult,
        startupHealthResult,
        healthResult,
        traceResult,
        contractResult,
        sessionResult,
      ] =
        await Promise.allSettled([
        getActivePipeline(ENTERPRISE_ID),
        getPipelineVersions(ENTERPRISE_ID),
        getStartupHealth(),
        getRuntimeHealth(),
        getLatestTrace(ENTERPRISE_ID),
        getExternalQueryContract(),
        getSession(),
      ]);
      const loadFailures: string[] = [];
      if (activePipelineResult.status === "fulfilled") {
        setPipeline(activePipelineResult.value);
      } else {
        loadFailures.push(`Pipeline: ${activePipelineResult.reason instanceof Error ? activePipelineResult.reason.message : "load failed"}`);
      }
      if (versionsResult.status === "fulfilled") {
        setPipelineVersions(versionsResult.value);
      } else {
        loadFailures.push(`Versions: ${versionsResult.reason instanceof Error ? versionsResult.reason.message : "load failed"}`);
      }
      if (startupHealthResult.status === "fulfilled") {
        setStartupHealth(startupHealthResult.value);
      } else {
        loadFailures.push(`Startup health: ${startupHealthResult.reason instanceof Error ? startupHealthResult.reason.message : "load failed"}`);
      }
      if (healthResult.status === "fulfilled") {
        setRuntimeHealth(healthResult.value);
      } else {
        loadFailures.push(`Runtime health: ${healthResult.reason instanceof Error ? healthResult.reason.message : "load failed"}`);
      }
      if (traceResult.status === "fulfilled") {
        setLatestTrace(traceResult.value);
      } else {
        loadFailures.push(`Latest trace: ${traceResult.reason instanceof Error ? traceResult.reason.message : "load failed"}`);
      }
      if (contractResult.status === "fulfilled") {
        setQueryContract(contractResult.value);
      } else {
        setQueryContract(null);
        loadFailures.push(`Query contract: ${contractResult.reason instanceof Error ? contractResult.reason.message : "load failed"}`);
      }
      if (sessionResult.status === "fulfilled") {
        setSession(sessionResult.value);
      } else {
        setSession(null);
        loadFailures.push(`Session: ${sessionResult.reason instanceof Error ? sessionResult.reason.message : "load failed"}`);
      }
      setTracePlayback([]);
      setErrorMessage(buildLoadWarnings(loadFailures));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Developer console failed to load");
    }
  }, []);

  useEffect(() => {
    return () => {
      traceSubscriptionRef.current?.();
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    void (async () => {
      if (!isMounted) {
        return;
      }
      await loadConsole();
    })();
    const pollTimer = window.setInterval(() => {
      if (isMounted) {
        void loadConsole();
      }
    }, 5000);
    return () => {
      isMounted = false;
      window.clearInterval(pollTimer);
    };
  }, [loadConsole]);

  useEffect(() => {
    traceSubscriptionRef.current?.();
    setTracePlayback([]);
    if (!latestTrace) {
      return;
    }
    traceSubscriptionRef.current = subscribeToTraceEvents(
      latestTrace.traceId,
      (event) => {
        setTracePlayback((currentEvents) => {
          const hasExistingEvent = currentEvents.some((currentEvent) => currentEvent.position === event.position);
          return hasExistingEvent ? currentEvents : [...currentEvents, event];
        });
      },
      () => undefined,
      (message) => setErrorMessage(message),
    );
    return () => {
      traceSubscriptionRef.current?.();
      traceSubscriptionRef.current = null;
    };
  }, [latestTrace?.traceId]);

  async function handleValidate(): Promise<void> {
    if (!session?.isAdmin) {
      setErrorMessage("Only administrators can validate pipeline changes.");
      return;
    }
    setPublishState("validating");
    setErrorMessage(null);
    try {
      const validatedPipeline = await validatePipeline(ENTERPRISE_ID);
      setPipeline(validatedPipeline);
      await loadConsole();
      setPublishState("saved");
    } catch (error) {
      setPublishState("saved");
      setErrorMessage(error instanceof Error ? error.message : "Pipeline validation failed");
    }
  }

  async function handlePublish(): Promise<void> {
    await handleActivateVersion();
  }

  async function handleActivateVersion(version?: number): Promise<void> {
    if (!session?.isAdmin) {
      setErrorMessage("Only administrators can activate pipeline versions.");
      return;
    }
    setPublishState("publishing");
    setErrorMessage(null);
    try {
      const activatedPipeline = await activatePipeline(ENTERPRISE_ID, version);
      setPipeline(activatedPipeline);
      await loadConsole();
      setPublishState("published");
    } catch (error) {
      setPublishState("saved");
      setErrorMessage(error instanceof Error ? error.message : "Pipeline activation failed");
    }
  }

  const runtimeSummary = runtimeHealth?.components.map((component) => component.status).join(", ");
  const latestVersion = pipelineVersions[0] ?? null;
  const consolePublicUrl = getConsolePublicUrl();
  const queryPublicUrl = getQueryPublicUrl();
  const deployedSurfaceConfig = parseDeploymentConfig(deploymentConfig?.detail);
  const effectiveConsoleUrl = deployedSurfaceConfig.consoleUrl ?? consolePublicUrl;
  const effectiveQueryUrl = deployedSurfaceConfig.queryUrl ?? queryPublicUrl;
  const surfaceDeploymentChecks = buildSurfaceDeploymentChecks(
    startupHealth?.environment ?? runtimeHealth?.environment,
    effectiveConsoleUrl,
    effectiveQueryUrl,
    deployedSurfaceConfig.startupPolicy,
    queryContract,
  );
  const packageReadinessStatus = startupHealth?.status ?? "loading";
  const liveReadinessStatus = runtimeHealth?.status ?? "loading";
  const latestTraceEventsPath = latestTrace
    ? `/v1/query/${latestTrace.traceId}/events`
    : "/v1/query/{traceId}/events";
  const retrievedEvidence = latestTrace?.retrievedEvidence ?? [];
  const contractHeaderNames = queryContract?.responseHeaders ?? [...EXTERNAL_QUERY_HEADER_NAMES];

  return (
    <main className="developer-console">
      <header className="developer-header">
        <div>
          <div className="breadcrumb">Pipelines / <strong>{pipeline?.name ?? "Enterprise evidence pipeline"}</strong></div>
          <div className="pipeline-title-row">
            <h1>{pipeline?.name ?? "Enterprise evidence pipeline"}</h1>
            <button className="version-button" type="button">v{pipeline?.version ?? 0} <CaretDown aria-hidden size={12} /></button>
            <span className="status-badge"><span /> {pipeline?.status ?? "loading"}</span>
          </div>
        </div>
        <div className="header-actions">
          <span className="save-state"><FloppyDisk aria-hidden size={15} />{publishState === "published" ? "Published" : publishState === "publishing" ? "Publishing…" : publishState === "validating" ? "Validating…" : "All changes saved"}</span>
          <button className="button button--secondary" type="button" onClick={() => void handleValidate()} disabled={!session?.isAdmin || publishState !== "saved"}>Validate</button>
          <button className="button button--primary" type="button" onClick={() => void handlePublish()} disabled={!session?.isAdmin || publishState !== "saved"}>Publish</button>
        </div>
      </header>

      <div className="developer-tabs" role="tablist" aria-label="Pipeline workspace">
        {["Graph", "Sources", "Jobs", "Configuration", "Evaluations", "Versions", "Settings"].map((tab) => (
          <button className={activeTab === tab ? "is-active" : ""} type="button" key={tab} onClick={() => setActiveTab(tab)}>{tab}</button>
        ))}
        <div className="metric-strip">
          <span><small>Startup</small><strong>{packageReadinessStatus}</strong></span>
          <span><small>Runtime</small><strong>{liveReadinessStatus}</strong></span>
          <span><small>Components</small><strong>{runtimeSummary ?? "checking"}</strong></span>
          <span><small>Alerts</small><strong>{runtimeAlerts.length}</strong></span>
          <span><small>Top-K</small><strong>{pipeline?.rerankTopK ?? 40}</strong></span>
          <span><small>Evidence</small><strong>{latestTrace?.evidenceStatus ?? "none"}</strong></span>
        </div>
      </div>

      <section className="developer-workspace">
        {activeTab === "Graph" ? (
          <>
            <div className="graph-region">
              <div className="graph-toolbar">
                <button type="button">+ Node</button><button type="button">+ Subgraph</button>
                <span className="graph-toolbar__notice"><ShieldCheck aria-hidden size={15} /> Mandatory controls locked</span>
              </div>
              <PipelineGraphCanvas selectedNodeId={selectedNodeId} onSelectNode={setSelectedNodeId} />
            </div>
            <aside className="node-inspector">
              <div className="inspector-tabs"><button className="is-active" type="button">Node</button><button type="button">Pipeline</button></div>
              <div className="inspector-heading"><span className="inspector-sequence">{Object.keys(inspectorContent).indexOf(selectedNodeId) + 1}</span><div><h2>{selectedInspector.title}</h2><span>Healthy · v1.0.0</span></div></div>
              <dl className="inspector-summary"><div><dt>Node type</dt><dd>{selectedInspector.type}</dd></div><div><dt>Behavior</dt><dd>{selectedInspector.detail}</dd></div></dl>
              <div className="inspector-section"><h3>Configuration</h3><label>Candidate limit<input value={selectedNodeId === "rerank" ? String(pipeline?.rerankTopK ?? 40) : "Required"} readOnly /></label><label>Execution profile<select defaultValue="balanced"><option value="balanced">Balanced</option><option value="fast">Speed</option><option value="accurate">Accuracy</option></select></label></div>
              <div className="inspector-section"><h3>Guardrails</h3><div className="guardrail-row"><CheckCircle aria-hidden weight="fill" />Authorization preserved</div><div className="guardrail-row"><CheckCircle aria-hidden weight="fill" />Audit emission enabled</div></div>
            </aside>
          </>
        ) : activeTab === "Sources" ? (
          <div className="developer-secondary-workspace">
            <SourceOperations enterpriseId={ENTERPRISE_ID} onJobQueued={(jobId) => setHighlightedJobId(jobId)} />
          </div>
        ) : activeTab === "Jobs" ? (
          <div className="developer-secondary-workspace">
            <JobOperations enterpriseId={ENTERPRISE_ID} highlightedJobId={highlightedJobId} />
          </div>
        ) : activeTab === "Versions" ? (
          <div className="developer-secondary-workspace">
            <section className="job-operations">
              <div className="section-heading">
                <CheckCircle aria-hidden size={18} />
                <strong>Pipeline versions</strong>
                <span>{pipelineVersions.length}</span>
              </div>
              <div className="metric-strip" style={{ marginBottom: 16 }}>
                <span><small>Active</small><strong>{activeVersion ? `v${activeVersion.version}` : "none"}</strong></span>
                <span><small>Validated</small><strong>{validatedVersions.length}</strong></span>
                <span><small>Rollback</small><strong>{rollbackCandidates.length}</strong></span>
                <span><small>Current top-K</small><strong>{pipeline?.rerankTopK ?? 40}</strong></span>
              </div>
              {validatedVersions.length > 0 ? (
                <div className="toast" style={{ position: "static", marginBottom: 16 }}>
                  <CheckCircle weight="fill" /> Version v{validatedVersions[0].version} is validated and ready for activation.
                </div>
              ) : null}
              {rollbackCandidates.length > 0 ? (
                <div className="source-form-card" style={{ marginBottom: 16 }}>
                  <div className="source-form-card__heading">
                    <Clock aria-hidden size={18} />
                    <strong>Rollback ready</strong>
                  </div>
                  <p>
                    Retired versions remain available for explicit rollback. Cortex only reactivates
                    immutable versions and preserves the audit trail for every activation.
                  </p>
                </div>
              ) : null}
              <table>
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Created by</th>
                    <th>Activated</th>
                    <th>Top-K</th>
                    <th>Definition hash</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {pipelineVersions.length > 0 ? (
                    pipelineVersions.map((version) => (
                      <tr key={version.pipelineVersionId}>
                        <td>v{version.version}</td>
                        <td>{version.status}</td>
                        <td>{version.createdBy}</td>
                        <td>{version.activatedAt ? new Date(version.activatedAt).toLocaleString() : "—"}</td>
                        <td>{version.rerankTopK}</td>
                        <td><code>{version.definitionHash.slice(0, 16)}</code></td>
                        <td>
                          {version.status === "validated" ? (
                            <button
                              className="button button--primary"
                              type="button"
                              onClick={() => void handleActivateVersion(version.version)}
                              disabled={!session?.isAdmin || publishState !== "saved"}
                            >
                              Promote
                            </button>
                          ) : version.status === "retired" ? (
                            <button
                              className="button button--secondary"
                              type="button"
                              onClick={() => void handleActivateVersion(version.version)}
                              disabled={!session?.isAdmin || publishState !== "saved"}
                            >
                              Roll back
                            </button>
                          ) : version.status === "active" ? (
                            <span>Live</span>
                          ) : (
                            <span>Awaiting validation</span>
                          )}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={7}>No persisted pipeline versions yet.</td></tr>
                  )}
                </tbody>
              </table>
            </section>
          </div>
        ) : activeTab === "Settings" ? (
          <div className="developer-secondary-workspace">
            <section className="job-operations">
              <div className="section-heading">
                <ShieldCheck aria-hidden size={18} />
                <strong>Deployment readiness</strong>
                <span>{liveReadinessStatus}</span>
              </div>
              <div className="metric-strip" style={{ marginBottom: 16 }}>
                <span><small>Startup</small><strong>{packageReadinessStatus}</strong></span>
                <span><small>Live</small><strong>{liveReadinessStatus}</strong></span>
                <span><small>Startup blockers</small><strong>{startupAlerts.length}</strong></span>
                <span><small>Live blockers</small><strong>{runtimeAlerts.length}</strong></span>
              </div>
              {startupAlerts.length > 0 ? (
                <div className="query-error" role="alert" style={{ marginBottom: 16 }}>
                  <WarningCircle aria-hidden size={18} />
                  <div>
                    <strong>Fail-closed startup gate</strong>
                    <span>
                      Packaged production boot should stop until these startup checks are clean:{" "}
                      {startupAlerts
                        .map((component) =>
                          component.remediation
                            ? `${component.name}: ${component.detail} Remediation: ${component.remediation}`
                            : `${component.name}: ${component.detail}`,
                        )
                        .join(" | ")}
                    </span>
                  </div>
                </div>
              ) : startupHealth ? (
                <div className="toast" style={{ position: "static", marginBottom: 16 }}>
                  <CheckCircle weight="fill" /> Static package startup contract is satisfied.
                </div>
              ) : null}
              <div className="source-form-card" style={{ marginBottom: 16 }}>
                <div className="source-form-card__heading">
                  <ShieldCheck aria-hidden size={18} />
                  <strong>Startup contract</strong>
                </div>
                <p>
                  These checks define whether a packaged production API should boot at all. They
                  cover split-host configuration, public URLs, object storage, parser dependencies,
                  accelerator expectations, and offline model-endpoint policy before live database
                  or Ollama dependency checks begin.
                </p>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Status</th>
                    <th>Severity</th>
                    <th>Detail</th>
                    <th>Remediation</th>
                  </tr>
                </thead>
                <tbody>
                  {startupHealth?.components.length ? (
                    startupHealth.components.map((component) => (
                      <tr key={component.name}>
                        <td>{component.name}</td>
                        <td>{component.status}</td>
                        <td>{component.severity}</td>
                        <td>{component.detail}</td>
                        <td>{component.remediation ?? "—"}</td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={5}>Startup readiness is still loading.</td></tr>
                  )}
                </tbody>
              </table>
              <div className="source-form-card" style={{ marginTop: 16, marginBottom: 16 }}>
                <div className="source-form-card__heading">
                  <Play aria-hidden size={18} />
                  <strong>Live readiness</strong>
                </div>
                <p>
                  These checks confirm the running package can actually serve and process work:
                  PostgreSQL/pgvector connectivity, model endpoint reachability, object storage
                  access, and other live runtime dependencies.
                </p>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Status</th>
                    <th>Severity</th>
                    <th>Detail</th>
                    <th>Remediation</th>
                  </tr>
                </thead>
                <tbody>
                  {runtimeHealth?.components.length ? (
                    runtimeHealth.components.map((component) => (
                      <tr key={component.name}>
                        <td>{component.name}</td>
                        <td>{component.status}</td>
                        <td>{component.severity}</td>
                        <td>{component.detail}</td>
                        <td>{component.remediation ?? "—"}</td>
                      </tr>
                    ))
                  ) : (
                    <tr><td colSpan={5}>Runtime readiness is still loading.</td></tr>
                  )}
                </tbody>
              </table>
              {runtimeAlerts.length > 0 ? (
                <div className="query-error" role="alert" style={{ marginTop: 16 }}>
                  <WarningCircle aria-hidden size={18} />
                  <div>
                    <strong>Runtime alerts</strong>
                    <span>
                      {runtimeAlerts
                        .map((component) =>
                          component.remediation
                            ? `${component.name}: ${component.detail} Remediation: ${component.remediation}`
                            : `${component.name}: ${component.detail}`,
                        )
                        .join(" | ")}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="toast" style={{ position: "static", marginTop: 16 }}>
                  <CheckCircle weight="fill" /> No runtime alerts detected.
                </div>
              )}
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <Clock aria-hidden size={18} />
                  <strong>Active release summary</strong>
                </div>
                <p>
                  Latest immutable version {latestVersion ? `v${latestVersion.version}` : "—"} with
                  rerank top-K {pipeline?.rerankTopK ?? 40}. The fixed console remains first-party;
                  client chat shells should integrate through the external query contract.
                </p>
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <Play aria-hidden size={18} />
                  <strong>Model profile</strong>
                </div>
                <p>{modelProfile?.detail ?? "Runtime profile is still loading."}</p>
                {modelProfile?.remediation ? (
                  <p style={{ marginTop: 8 }}><strong>Operator note:</strong> {modelProfile.remediation}</p>
                ) : null}
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <Clock aria-hidden size={18} />
                  <strong>Package build profile</strong>
                </div>
                <p>{packageBuildProfile?.detail ?? "Packaged build profile is still loading."}</p>
                {packageBuildProfile?.remediation ? (
                  <p style={{ marginTop: 8 }}><strong>Operator note:</strong> {packageBuildProfile.remediation}</p>
                ) : null}
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <ShieldCheck aria-hidden size={18} />
                  <strong>Identity profile</strong>
                </div>
                <p>{identityProfile?.detail ?? "Identity contract is still loading."}</p>
                {identityProfile?.remediation ? (
                  <p style={{ marginTop: 8 }}><strong>Operator note:</strong> {identityProfile.remediation}</p>
                ) : null}
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <ShieldCheck aria-hidden size={18} />
                  <strong>Surface routing</strong>
                </div>
                <p>
                  Console host: <code>{effectiveConsoleUrl}</code><br />
                  Query host: <code>{effectiveQueryUrl}</code><br />
                  The console stays fixed; the bundled query UI is optional and may be replaced.
                </p>
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <ShieldCheck aria-hidden size={18} />
                  <strong>Surface deployment contract</strong>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>Status</th>
                      <th>Detail</th>
                      <th>Remediation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {surfaceDeploymentChecks.map((check) => (
                      <tr key={check.label}>
                        <td>{check.label}</td>
                        <td>{check.status}</td>
                        <td>{check.detail}</td>
                        <td>{check.remediation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <Play aria-hidden size={18} />
                  <strong>Client query contract</strong>
                </div>
                <p>
                  Contract {queryContract?.contractVersion ?? EXTERNAL_QUERY_CONTRACT_VERSION} lives at{" "}
                  <code>
                    {queryContract?.method ?? "POST"}{" "}
                    {queryContract?.endpointPath ?? "/v1/chat/completions"}
                  </code>.
                  Replacement UIs should preserve <code>x_cortex.traceId</code>, evidence
                  status, abstention state, and citations from the response payload.
                </p>
                <p style={{ marginTop: 8 }}>
                  Authentication is <code>{queryContract?.authentication ?? "bearer-token"}</code>.
                  Streaming support is <code>{String(queryContract?.supportsStreaming ?? false)}</code>.
                  Trace replay remains reserved for operator tooling at{" "}
                  <code>
                    {queryContract?.traceEventsPathTemplate ?? "/v1/query/{traceId}/events"}
                  </code>, and the fixed console lives at{" "}
                  <code>{queryContract?.operatorConsolePath ?? "/developer"}</code>.
                </p>
                {queryContract ? (
                  <div style={{ marginTop: 12 }}>
                    <strong>Request behavior</strong>
                    <p style={{ marginTop: 6 }}>
                      Query selection policy{" "}
                      <code>{queryContract.requestOptions.userMessageSelectionPolicy}</code>.
                      Required stream value <code>{String(queryContract.requestOptions.streamRequiredValue)}</code>.
                      Citation toggle preserved <code>{String(queryContract.requestOptions.supportsCitationToggle)}</code>.
                    </p>
                    <strong>Employee-safe fields</strong>
                    <p style={{ marginTop: 6 }}>
                      {queryContract.employeeSafeExtensionFields.map((fieldName) => (
                        <code key={fieldName} style={{ marginRight: 8 }}>
                          x_cortex.{fieldName}
                        </code>
                      ))}
                    </p>
                    <strong>Operator-only fields</strong>
                    <p style={{ marginTop: 6 }}>
                      {queryContract.operatorOnlyExtensionFields.map((fieldName) => (
                        <code key={fieldName} style={{ marginRight: 8 }}>
                          x_cortex.{fieldName}
                        </code>
                      ))}
                    </p>
                    <strong>Extension fields</strong>
                    <p style={{ marginTop: 6 }}>
                      {queryContract.extensionFields.map((fieldName) => (
                        <code key={fieldName} style={{ marginRight: 8 }}>
                          x_cortex.{fieldName}
                        </code>
                      ))}
                    </p>
                    <strong>Abstention evidence states</strong>
                    <p style={{ marginTop: 6 }}>
                      {queryContract.abstentionEvidenceStatuses.map((statusName) => (
                        <code key={statusName} style={{ marginRight: 8 }}>
                          {statusName}
                        </code>
                      ))}
                    </p>
                    <strong>Error statuses</strong>
                    <table style={{ marginTop: 10 }}>
                      <thead>
                        <tr>
                          <th>Status</th>
                          <th>Code</th>
                          <th>Retryable</th>
                          <th>Meaning</th>
                        </tr>
                      </thead>
                      <tbody>
                        {queryContract.errorStatuses.map((errorStatus) => (
                          <tr key={errorStatus.code}>
                            <td>{errorStatus.statusCode}</td>
                            <td><code>{errorStatus.code}</code></td>
                            <td>{String(errorStatus.retryable)}</td>
                            <td>{errorStatus.meaning}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
              <div className="source-form-card" style={{ marginTop: 16 }}>
                <div className="source-form-card__heading">
                  <Clock aria-hidden size={18} />
                  <strong>Contract headers</strong>
                </div>
                <p>
                  Thin clients, gateways, and observability hooks can inspect stable response headers
                  before parsing the JSON body:
                </p>
                <ul style={{ marginTop: 10, paddingLeft: 18 }}>
                  {contractHeaderNames.map((headerName) => (
                    <li key={headerName}><code>{headerName}</code></li>
                  ))}
                </ul>
              </div>
              {queryContract?.notes.length ? (
                <div className="source-form-card" style={{ marginTop: 16 }}>
                  <div className="source-form-card__heading">
                    <ShieldCheck aria-hidden size={18} />
                    <strong>Contract guidance</strong>
                  </div>
                  <ul style={{ marginTop: 10, paddingLeft: 18 }}>
                    {queryContract.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          </div>
        ) : (
          <div className="developer-secondary-workspace">
            <div className="empty-tab"><CheckCircle size={36} weight="duotone" /><h2>{activeTab}</h2><p>This workspace is connected to the selected immutable pipeline version.</p></div>
          </div>
        )}
      </section>

      <section className="execution-trace">
        <div className="trace-heading"><div><Play aria-hidden size={17} weight="fill" /><strong>Execution trace</strong><code>{latestTrace ? latestTrace.traceId.slice(0, 12) : "waiting"}</code></div><span>{latestTrace ? <><CheckCircle aria-hidden size={16} weight="fill" /> {latestTrace.outcome}</> : <>No trace yet</>}</span></div>
        <div className="trace-query"><Clock aria-hidden size={15} /> User query: <strong>{latestTrace?.rawQuery ?? "Seed the corpus or run a query to populate the trace timeline."}</strong></div>
        {latestTrace?.correctedQuery && latestTrace.correctedQuery !== latestTrace.rawQuery ? (
          <div className="trace-query"><CheckCircle aria-hidden size={15} /> Corrected query: <strong>{latestTrace.correctedQuery}</strong></div>
        ) : null}
        {latestTrace?.answer ? (
          <div className="source-form-card" style={{ marginTop: 12, marginBottom: 12 }}>
            <div className="source-form-card__heading">
              <Play aria-hidden size={18} />
              <strong>Validated answer preview</strong>
            </div>
            <p style={{ marginTop: 10 }}>{latestTrace.answer}</p>
          </div>
        ) : null}
        {latestTrace ? (
          <div className="source-form-card" style={{ marginTop: 12, marginBottom: 12 }}>
            <div className="source-form-card__heading">
              <ShieldCheck aria-hidden size={18} />
              <strong>Operator correlation</strong>
            </div>
            <p>
              Trace <code>{latestTrace.traceId}</code> can be handed to support workflows, client
              feedback queues, or replacement query UIs as the durable correlation key.
            </p>
            <p style={{ marginTop: 8 }}>
              Route <code>{latestTrace.route}</code> · trace events <code>{latestTraceEventsPath}</code>
            </p>
          </div>
        ) : null}
        {latestTrace ? (
          <div className="metric-strip metric-strip--trace">
            <span><small>Actor</small><strong>{latestTrace.actorId}</strong></span>
            <span><small>Started</small><strong>{new Date(latestTrace.createdAt).toLocaleTimeString()}</strong></span>
            <span><small>Route</small><strong>{latestTrace.route}</strong></span>
            <span><small>Evidence</small><strong>{latestTrace.evidenceStatus}</strong></span>
            <span><small>Stages</small><strong>{displayedEvents.length}</strong></span>
            <span><small>Claims</small><strong>{latestTrace.claims.length}</strong></span>
            <span><small>Citations</small><strong>{latestTrace.citations.length}</strong></span>
            <span><small>Pipeline</small><strong>v{latestTrace.pipelineVersion ?? 0}</strong></span>
            <span><small>Evidence rows</small><strong>{retrievedEvidence.length}</strong></span>
          </div>
        ) : null}
        {latestTrace && latestTrace.outcome !== "sufficient" ? (
          <div className="query-error" role="alert">
            <WarningCircle aria-hidden size={18} />
            <div>
              <strong>Trace outcome requires operator review</strong>
              <span>
                Latest trace finished with outcome {latestTrace.outcome}. Review stage detail,
                evidence status, and citations before promoting or troubleshooting this flow.
              </span>
            </div>
          </div>
        ) : null}
        {errorMessage ? <div className="query-error" role="alert"><WarningCircle aria-hidden size={18} /><div><strong>Console warning</strong><span>{errorMessage}</span></div></div> : null}
        <table><thead><tr><th>Stage</th><th>Status</th><th>Duration</th><th>Detail</th><th>Evidence</th></tr></thead><tbody>{displayedEvents.length > 0 ? displayedEvents.map((row) => <tr key={`${row.position}-${row.stage}`}><td>{row.stage}</td><td><span className="table-success"><CheckCircle aria-hidden weight="fill" /> {row.status}</span></td><td>{row.durationMs}ms</td><td>{row.detail}</td><td>{latestTrace?.citations.length ?? 0} citations</td></tr>) : <tr><td colSpan={5}>No persisted execution trace yet.</td></tr>}</tbody></table>
        {latestTrace?.claims.length ? (
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Support</th>
                <th>Confidence</th>
                <th>Citations</th>
              </tr>
            </thead>
            <tbody>
              {latestTrace.claims.map((claim) => (
                <tr key={claim.claimId}>
                  <td>{claim.text}</td>
                  <td>{claim.supportStatus}</td>
                  <td>{claim.confidence.toFixed(2)}</td>
                  <td>{claim.citationIds.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {latestTrace?.citations.length ? (
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Citation</th>
                <th>Document</th>
                <th>Locator</th>
                <th>Support</th>
              </tr>
            </thead>
            <tbody>
              {latestTrace.citations.map((citation) => (
                <tr key={citation.citationId}>
                  <td>{citation.citationId}</td>
                  <td>{citation.documentTitle}</td>
                  <td>{citation.structuralLocator}</td>
                  <td>{citation.supportScore.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {retrievedEvidence.length ? (
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Evidence chunk</th>
                <th>Locator</th>
                <th>Scores</th>
                <th>Preview</th>
              </tr>
            </thead>
            <tbody>
              {retrievedEvidence.map((evidenceRow) => (
                <tr key={evidenceRow.chunkId}>
                  <td>
                    <strong>{evidenceRow.documentTitle}</strong>
                    <div>
                      <small>{evidenceRow.documentVersion}</small>
                    </div>
                  </td>
                  <td>{evidenceRow.structuralLocator || "—"}</td>
                  <td>
                    support {evidenceRow.supportScore.toFixed(2)}
                    <br />
                    rerank {evidenceRow.rerankScore.toFixed(2)} · source{" "}
                    {evidenceRow.sourceScore.toFixed(2)}
                  </td>
                  <td>{evidenceRow.contentPreview}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      {publishState === "published" ? <div className="toast"><CheckCircle weight="fill" /> Pipeline v{pipeline?.version ?? 0} published</div> : null}
      {publishState === "validating" ? <div className="toast toast--warning"><WarningCircle weight="fill" /> Running promotion gates</div> : null}
      {publishState === "publishing" ? <div className="toast toast--warning"><WarningCircle weight="fill" /> Activating immutable pipeline version</div> : null}
    </main>
  );
}
