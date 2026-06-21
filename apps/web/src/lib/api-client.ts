/** Centralizes typed API operations so transport failures remain visible to users. */

import type {
  CreateWebsiteSourceRequest,
  CreateWebsiteSourceResponse,
  CreateUploadSourceResponse,
  JobStatus,
  JobSummary,
  PipelineGraph,
  QueryRequest,
  QueryResponse,
  QueryStageEvent,
  RuntimeHealth,
  SourceDetail,
  SourceSummary,
  TraceSummary,
} from "../types";

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
    const response = await fetch(path, init);
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

/** Load the immutable active pipeline definition for the developer graph. */
export async function getActivePipeline(): Promise<PipelineGraph> {
  return fetchJson<PipelineGraph>("/v1/pipelines/active");
}

/** Load the latest persisted trace for the selected enterprise. */
export async function getLatestTrace(enterpriseId: string): Promise<TraceSummary | null> {
  return fetchJson<TraceSummary | null>(`/v1/traces/latest?enterpriseId=${enterpriseId}`);
}

/** Check the live runtime dependencies backing the current environment. */
export async function getRuntimeHealth(): Promise<RuntimeHealth> {
  return fetchJson<RuntimeHealth>("/health/ready");
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
  actorId: string;
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
  formData.set("actorId", request.actorId);
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
