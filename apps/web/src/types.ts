/** UI aliases reference generated OpenAPI contracts instead of duplicating wire schemas. */

import type { components } from "./generated/cortex-api";

export type Surface = "developer" | "query";

export type Citation = components["schemas"]["CitationSchema"];
export type Claim = components["schemas"]["ClaimSchema"];
export type QueryStage = components["schemas"]["StageSchema"];
export type QueryStageEvent = components["schemas"]["QueryStageEventSchema"];
export type QueryResponse = components["schemas"]["QueryResponse"];
export type QueryRequest = components["schemas"]["QueryRequest"];
export type TraceSummary = components["schemas"]["TraceSummaryResponse"];
export type RuntimeHealth = components["schemas"]["RuntimeHealthResponse"];
export type PipelineGraph = components["schemas"]["PipelineGraphResponse"];
