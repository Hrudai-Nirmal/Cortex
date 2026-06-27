/** Centralizes typed API operations so transport failures remain visible to users. */

import { getActiveSurface } from "../config";
import type {
  CreateWebsiteSourceRequest,
  CreateWebsiteSourceResponse,
  CreateUploadSourceResponse,
  ExternalQueryContractDescriptor,
  ExternalChatCompletionResponse,
  JobStatus,
  JobSummary,
  PipelineGraph,
  PipelineVersionSummary,
  QueryRequest,
  QueryResponse,
  QueryStageEvent,
  RuntimeHealth,
  Session,
  SourceDetail,
  SourceSummary,
  TraceSummary,
} from "../types";

const BUNDLED_QUERY_CONTRACT_VERSION = "v1";
const REQUIRED_QUERY_EXTENSION_FIELDS = [
  "contractVersion",
  "traceId",
  "route",
  "evidenceStatus",
  "abstained",
  "claims",
  "citations",
  "stages",
] as const;
const REQUIRED_OPERATOR_ONLY_EXTENSION_FIELDS = ["traceEventsPath"] as const;
const REQUIRED_QUERY_RESPONSE_HEADERS = [
  "X-Cortex-Contract-Version",
  "X-Cortex-Trace-Id",
  "X-Cortex-Evidence-Status",
  "X-Cortex-Route",
  "X-Cortex-Abstained",
] as const;
const REQUIRED_QUERY_ERROR_CODES = [
  "invalid_request",
  "forbidden_scope",
  "provider_unavailable",
  "internal_error",
] as const;
const REQUIRED_QUERY_EVIDENCE_STATUSES = [
  "sufficient",
  "partial",
  "insufficient",
  "conflict",
] as const;
const REQUIRED_QUERY_ROUTES = ["rag", "compute", "retrieve-then-compute"] as const;
const REQUIRED_QUERY_ABSTENTION_EVIDENCE_STATUSES = ["insufficient", "conflict"] as const;

function getDefaultFixtureToken(): string {
  return getActiveSurface() === "query" ? "fixture-employee" : "fixture-admin";
}

function buildHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  if (!headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${getDefaultFixtureToken()}`);
  }
  return headers;
}

async function parseFailure(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(path, {
      ...init,
      headers: buildHeaders(init?.headers),
    });
    if (!response.ok) {
      throw new Error(await parseFailure(response));
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new Error(error instanceof Error ? error.message : `Cortex request failed for ${path}`);
  }
}

function buildContractCompatibilityError(message: string): Error {
  return new Error(`This Cortex query surface is incompatible with the deployed package. ${message}`);
}

function validateExternalQueryContractDescriptor(
  descriptor: ExternalQueryContractDescriptor,
): ExternalQueryContractDescriptor {
  if (descriptor.contractVersion !== BUNDLED_QUERY_CONTRACT_VERSION) {
    throw buildContractCompatibilityError("Expected query contract v1.");
  }
  if (descriptor.method !== "POST" || descriptor.endpointPath !== "/v1/chat/completions") {
    throw buildContractCompatibilityError("The deployed query endpoint does not match the bundled UI contract.");
  }
  if (descriptor.authentication !== "bearer-token") {
    throw buildContractCompatibilityError("The deployed query authentication mode is unsupported.");
  }
  if (descriptor.supportsStreaming) {
    throw buildContractCompatibilityError("The bundled query UI only supports non-streaming Cortex chat responses.");
  }
  if (descriptor.requestOptions.userMessageSelectionPolicy !== "last-non-empty-user-message") {
    throw buildContractCompatibilityError("The deployed query message-selection policy is unsupported.");
  }
  if (descriptor.requestOptions.streamRequiredValue !== false) {
    throw buildContractCompatibilityError("The deployed query contract no longer guarantees stream=false requests.");
  }
  if (!descriptor.requestOptions.supportsCitationToggle) {
    throw buildContractCompatibilityError("The deployed query contract does not preserve the citation display toggle.");
  }
  if (!["bundled", "external"].includes(descriptor.querySurfaceMode)) {
    throw buildContractCompatibilityError("The deployed query-surface mode is unsupported.");
  }
  if (descriptor.querySurfaceMode === "bundled" && !descriptor.bundledQueryUiAvailable) {
    throw buildContractCompatibilityError("The deployed package reports a bundled query UI mismatch.");
  }
  if (descriptor.querySurfaceMode === "external" && descriptor.bundledQueryUiAvailable) {
    throw buildContractCompatibilityError("The deployed package reports an external query mode mismatch.");
  }
  for (const requiredField of REQUIRED_QUERY_EXTENSION_FIELDS) {
    if (!descriptor.employeeSafeExtensionFields.includes(requiredField)) {
      throw buildContractCompatibilityError(`Missing required employee-safe Cortex field: ${requiredField}.`);
    }
    if (!descriptor.extensionFields.includes(requiredField)) {
      throw buildContractCompatibilityError(`Missing required Cortex extension field: ${requiredField}.`);
    }
  }
  for (const operatorOnlyField of REQUIRED_OPERATOR_ONLY_EXTENSION_FIELDS) {
    if (!descriptor.operatorOnlyExtensionFields.includes(operatorOnlyField)) {
      throw buildContractCompatibilityError(`Missing required operator-only Cortex field: ${operatorOnlyField}.`);
    }
  }
  for (const requiredHeader of REQUIRED_QUERY_RESPONSE_HEADERS) {
    if (!descriptor.responseHeaders.includes(requiredHeader)) {
      throw buildContractCompatibilityError(`Missing required Cortex response header: ${requiredHeader}.`);
    }
  }
  for (const requiredCode of REQUIRED_QUERY_ERROR_CODES) {
    if (!descriptor.errorStatuses.some((errorStatus) => errorStatus.code === requiredCode)) {
      throw buildContractCompatibilityError(`Missing required Cortex error contract entry: ${requiredCode}.`);
    }
  }
  for (const requiredEvidenceStatus of REQUIRED_QUERY_EVIDENCE_STATUSES) {
    if (!descriptor.evidenceStatuses.includes(requiredEvidenceStatus)) {
      throw buildContractCompatibilityError(`Missing required Cortex evidence status: ${requiredEvidenceStatus}.`);
    }
  }
  for (const requiredRoute of REQUIRED_QUERY_ROUTES) {
    if (!descriptor.routes.includes(requiredRoute)) {
      throw buildContractCompatibilityError(`Missing required Cortex route: ${requiredRoute}.`);
    }
  }
  for (const requiredAbstentionStatus of REQUIRED_QUERY_ABSTENTION_EVIDENCE_STATUSES) {
    if (!descriptor.abstentionEvidenceStatuses.includes(requiredAbstentionStatus)) {
      throw buildContractCompatibilityError(
        `Missing required Cortex abstention evidence status: ${requiredAbstentionStatus}.`,
      );
    }
  }
  return descriptor;
}

function validateExternalChatResponse(
  response: ExternalChatCompletionResponse,
  descriptor: ExternalQueryContractDescriptor,
  headers: Headers,
): QueryResponse {
  for (const requiredField of REQUIRED_QUERY_EXTENSION_FIELDS) {
    if (!(requiredField in response.x_cortex)) {
      throw buildContractCompatibilityError(`The response is missing required Cortex field: ${requiredField}.`);
    }
  }
  if (response.x_cortex.contractVersion !== descriptor.contractVersion) {
    throw buildContractCompatibilityError("The response contract version does not match the live descriptor.");
  }
  if (!descriptor.routes.includes(response.x_cortex.route)) {
    throw buildContractCompatibilityError("The response route is outside the deployed Cortex contract.");
  }
  if (!descriptor.evidenceStatuses.includes(response.x_cortex.evidenceStatus)) {
    throw buildContractCompatibilityError("The response evidence status is outside the deployed Cortex contract.");
  }
  if (
    response.x_cortex.abstained
    && !descriptor.abstentionEvidenceStatuses.some(
      (status) => status === response.x_cortex.evidenceStatus,
    )
  ) {
    throw buildContractCompatibilityError("The response abstention state does not match the deployed evidence contract.");
  }
  if (
    !response.x_cortex.abstained
    && descriptor.abstentionEvidenceStatuses.some(
      (status) => status === response.x_cortex.evidenceStatus,
    )
  ) {
    throw buildContractCompatibilityError("The response abstention state is inconsistent with the deployed evidence contract.");
  }
  const contractHeader = headers.get("X-Cortex-Contract-Version");
  if (contractHeader !== descriptor.contractVersion) {
    throw buildContractCompatibilityError("The response headers do not match the advertised Cortex contract version.");
  }
  const traceIdHeader = headers.get("X-Cortex-Trace-Id");
  if (!traceIdHeader || traceIdHeader !== response.x_cortex.traceId) {
    throw buildContractCompatibilityError("The response trace identifier is missing or inconsistent.");
  }
  const evidenceStatusHeader = headers.get("X-Cortex-Evidence-Status");
  if (!evidenceStatusHeader || evidenceStatusHeader !== response.x_cortex.evidenceStatus) {
    throw buildContractCompatibilityError("The response evidence status is missing or inconsistent.");
  }
  const routeHeader = headers.get("X-Cortex-Route");
  if (!routeHeader || routeHeader !== response.x_cortex.route) {
    throw buildContractCompatibilityError("The response route header is missing or inconsistent.");
  }
  const abstainedHeader = headers.get("X-Cortex-Abstained");
  const expectedAbstained = String(response.x_cortex.abstained);
  if (!abstainedHeader || abstainedHeader !== expectedAbstained) {
    throw buildContractCompatibilityError("The response abstention header is missing or inconsistent.");
  }
  return {
    traceId: response.x_cortex.traceId,
    route: response.x_cortex.route,
    correctedQuery: response.x_cortex.correctedQuery,
    answer: response.choices[0]?.message.content ?? "",
    evidenceStatus: response.x_cortex.evidenceStatus,
    claims: response.x_cortex.claims,
    citations: response.x_cortex.citations,
    stages: response.x_cortex.stages,
  };
}

/** Resolve the current authenticated browser identity for the active surface. */
export async function getSession(): Promise<Session> {
  return fetchJson<Session>("/v1/session");
}

/** Submit a query and return only the API's validated answer contract. */
export async function submitQuery(
  request: QueryRequest,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  return fetchJson<QueryResponse>("/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
}

/** Submit one authenticated chat turn through the replacement-query OpenAI facade. */
export async function submitChatQuery(
  query: string,
  showCitations: boolean,
  descriptor: ExternalQueryContractDescriptor,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  const validatedDescriptor = validateExternalQueryContractDescriptor(descriptor);
  try {
    const httpResponse = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: buildHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        model: "cortex-bounded-rag",
        messages: [{ role: "user", content: query }],
        stream: false,
        cortex: { showCitations },
      }),
      signal,
    });
    if (!httpResponse.ok) {
      throw new Error(await parseFailure(httpResponse));
    }
    const response = (await httpResponse.json()) as ExternalChatCompletionResponse;
    return validateExternalChatResponse(response, validatedDescriptor, httpResponse.headers);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new Error(
      error instanceof Error ? error.message : "Cortex chat request failed.",
    );
  }
}

/** Load the live replacement-query contract descriptor exported by Cortex. */
export async function getExternalQueryContract(): Promise<ExternalQueryContractDescriptor> {
  return validateExternalQueryContractDescriptor(
    await fetchJson<ExternalQueryContractDescriptor>("/v1/chat/contracts/v1"),
  );
}

/** Load the immutable active pipeline definition for the developer graph. */
export async function getActivePipeline(enterpriseId: string): Promise<PipelineGraph> {
  return fetchJson<PipelineGraph>(`/v1/pipelines/active?enterpriseId=${enterpriseId}`);
}

/** Validate the next persisted pipeline draft for the selected enterprise. */
export async function validatePipeline(enterpriseId: string): Promise<PipelineGraph> {
  return fetchJson<PipelineGraph>("/v1/pipelines/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enterpriseId }),
  });
}

/** Activate the newest validated pipeline or a specific rollback target. */
export async function activatePipeline(
  enterpriseId: string,
  version?: number,
): Promise<PipelineGraph> {
  return fetchJson<PipelineGraph>("/v1/pipelines/activate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enterpriseId, version: version ?? null }),
  });
}

/** List immutable pipeline versions for governance views or rollback controls. */
export async function getPipelineVersions(enterpriseId: string): Promise<PipelineVersionSummary[]> {
  return fetchJson<PipelineVersionSummary[]>(`/v1/pipelines/versions?enterpriseId=${enterpriseId}`);
}

/** Load the latest persisted trace for the selected enterprise. */
export async function getLatestTrace(enterpriseId: string): Promise<TraceSummary | null> {
  return fetchJson<TraceSummary | null>(`/v1/traces/latest?enterpriseId=${enterpriseId}`);
}

/** Check the live runtime dependencies backing the current environment. */
export async function getRuntimeHealth(): Promise<RuntimeHealth> {
  return fetchJson<RuntimeHealth>("/health/ready");
}

/** Check the static package startup contract without touching live dependencies. */
export async function getStartupHealth(): Promise<RuntimeHealth> {
  return fetchJson<RuntimeHealth>("/health/startup");
}

/** Load the current source inventory shown in the developer operations surface. */
export async function getSources(enterpriseId: string): Promise<SourceSummary[]> {
  return fetchJson<SourceSummary[]>(`/v1/sources?enterpriseId=${enterpriseId}`);
}

/** Load one source and its full version history for the developer detail pane. */
export async function getSourceDetail(
  enterpriseId: string,
  documentId: string,
): Promise<SourceDetail> {
  return fetchJson<SourceDetail>(`/v1/sources/${documentId}?enterpriseId=${enterpriseId}`);
}

/** Load the newest durable jobs for the developer jobs panel. */
export async function getJobs(enterpriseId: string): Promise<JobSummary[]> {
  return fetchJson<JobSummary[]>(`/v1/jobs?enterpriseId=${enterpriseId}`);
}

/** Load one durable job for focused polling or failure inspection. */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
  return fetchJson<JobStatus>(`/v1/jobs/${jobId}`);
}

/** Submit one file upload source and return the queued deterministic identifiers. */
export async function createUploadSource(request: {
  displayName: string;
  documentId?: string;
  enterpriseId: string;
  extractionQuality?: number;
  file: File;
  metadata?: Record<string, unknown>;
  principalIds: string[];
  publishedAt?: string;
  sourceAuthority?: number;
  versionLabel: string;
}): Promise<CreateUploadSourceResponse> {
  const formData = new FormData();
  formData.set("enterpriseId", request.enterpriseId);
  formData.set("displayName", request.displayName);
  formData.set("versionLabel", request.versionLabel);
  formData.set("principalIds", JSON.stringify(request.principalIds));
  formData.set("file", request.file);
  if (request.documentId) {
    formData.set("documentId", request.documentId);
  }
  if (request.sourceAuthority !== undefined) {
    formData.set("sourceAuthority", String(request.sourceAuthority));
  }
  if (request.extractionQuality !== undefined) {
    formData.set("extractionQuality", String(request.extractionQuality));
  }
  if (request.publishedAt) {
    formData.set("publishedAt", request.publishedAt);
  }
  if (request.metadata) {
    formData.set("metadata", JSON.stringify(request.metadata));
  }
  return fetchJson<CreateUploadSourceResponse>("/v1/sources/uploads", {
    method: "POST",
    body: formData,
  });
}

/** Submit one allowlisted website source and return the queued deterministic identifiers. */
export async function createWebsiteSource(
  request: CreateWebsiteSourceRequest,
): Promise<CreateWebsiteSourceResponse> {
  return fetchJson<CreateWebsiteSourceResponse>("/v1/sources/website", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** Subscribe to persisted stage events for developer-side trace playback. */
export function subscribeToTraceEvents(
  traceId: string,
  onStage: (event: QueryStageEvent) => void,
  onComplete: () => void,
  onError: (message: string) => void,
): () => void {
  const eventSource = new EventSource(`/v1/query/${traceId}/events`);
  eventSource.addEventListener("stage", (event) => {
    try {
      const payload = JSON.parse((event as MessageEvent<string>).data) as QueryStageEvent;
      onStage(payload);
    } catch {
      onError("Trace event payload was invalid");
    }
  });
  eventSource.addEventListener("complete", () => {
    onComplete();
    eventSource.close();
  });
  eventSource.onerror = () => {
    onError("Trace event stream disconnected");
    eventSource.close();
  };
  return () => eventSource.close();
}
