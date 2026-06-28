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
export type ExternalChatCompletionResponse = components["schemas"]["ChatCompletionResponseSchema"];
export type ExternalQueryContractDescriptor =
  components["schemas"]["ExternalQueryContractDescriptorSchema"];
export type RetrievedEvidence = components["schemas"]["RetrievedEvidenceSchema"];

export interface QueryContractSchemaDocument {
  title: string;
  properties: Record<string, unknown>;
}
