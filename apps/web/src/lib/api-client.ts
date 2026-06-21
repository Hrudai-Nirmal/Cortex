/** Centralizes typed API operations so transport failures remain visible to users. */

import type {
  PipelineGraph,
  QueryRequest,
  QueryResponse,
  QueryStageEvent,
  RuntimeHealth,
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
