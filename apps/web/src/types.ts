/** UI aliases reference generated OpenAPI contracts instead of duplicating wire schemas. */

import type { components } from "./generated/cortex-api";

export type Surface = "developer" | "query";

export type Citation = components["schemas"]["CitationSchema"];
export type Claim = components["schemas"]["ClaimSchema"];
export type QueryStage = components["schemas"]["StageSchema"];
export type QueryStageEvent = components["schemas"]["QueryStageEventSchema"];
export type QueryResponse = components["schemas"]["QueryResponse"];
export type QueryRequest = components["schemas"]["QueryRequest"];
export type Session = components["schemas"]["SessionResponse"];
export type TraceSummary = components["schemas"]["TraceSummaryResponse"];
export type RuntimeHealth = components["schemas"]["RuntimeHealthResponse"];
export type PipelineGraph = components["schemas"]["PipelineGraphResponse"];
export type PipelineVersionSummary = components["schemas"]["PipelineVersionSummaryResponse"];
export type SourceSummary = components["schemas"]["SourceSummaryResponse"];
export type SourceDetail = components["schemas"]["SourceDetailResponse"];
export type SourceVersion = components["schemas"]["SourceVersionResponse"];
export type CreateWebsiteSourceRequest = components["schemas"]["CreateWebsiteSourceRequest"];
export type CreateWebsiteSourceResponse = components["schemas"]["CreateWebsiteSourceResponse"];
export type CreateUploadSourceResponse = components["schemas"]["CreateUploadSourceResponse"];
export type JobStatus = components["schemas"]["JobStatusResponse"];
export type JobSummary = components["schemas"]["JobSummaryResponse"];

export interface ExternalChatCompletionResponse {
  id: string;
  object: "chat.completion";
  created: number;
  model: string;
  choices: Array<{
    index: number;
    message: {
      role: "assistant";
      content: string;
    };
    finish_reason: "stop";
  }>;
  x_cortex: {
    traceId: string;
    route: QueryResponse["route"];
    correctedQuery: QueryResponse["correctedQuery"];
    evidenceStatus: QueryResponse["evidenceStatus"];
    abstained: boolean;
    claims: QueryResponse["claims"];
    citations: QueryResponse["citations"];
    stages: QueryResponse["stages"];
  };
}
