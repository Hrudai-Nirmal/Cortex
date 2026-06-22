# External Query Contract

## Purpose

Cortex ships a bundled `query-web` surface, but enterprise clients may replace it with
their own chat shell. The supported integration boundary for those clients is:

- `POST /v1/chat/completions`

This route is intentionally OpenAI-compatible enough for standard chat UIs while adding
the Cortex evidence metadata a governed RAG system needs.

## Authentication and scope

Replacement query shells must send the same bearer token they use for the employee user.
Cortex derives:

- `enterpriseId`
- `actorId`
- ACL principals
- builder/admin restrictions where relevant

from the authenticated token on the server side.

Client UIs should not send raw retrieval scope, principals, or tenant filters from the
browser. That keeps scoped SQL retrieval as a server-enforced invariant instead of a UI
convention.

## Request

`POST /v1/chat/completions`

Example request:

```json
{
  "model": "cortex-bounded-rag",
  "messages": [
    { "role": "user", "content": "What are our data retention rules?" }
  ],
  "stream": false,
  "cortex": {
    "showCitations": true
  }
}
```

Notes:

- Cortex currently uses the last non-empty `user` message as the deterministic query input.
- `stream=true` is not supported on this facade.
- Stage progress remains available through persisted trace events rather than token streaming.
- `GET /v1/query/{traceId}/events` is a builder/operator trace surface, not an employee-client browser API.
- Replacement employee chat shells should use the returned `traceId` for correlation, feedback, and support escalation rather than attempting to replay trace events directly.

## Response

Example response:

```json
{
  "id": "cortex-4576b626-c27a-4409-9a51-600cf115ff4a",
  "object": "chat.completion",
  "created": 1718928000,
  "model": "cortex-bounded-rag",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Raw query content is retained for 30 days."
      },
      "finish_reason": "stop"
    }
  ],
  "x_cortex": {
    "contractVersion": "v1",
    "traceId": "4576b626-c27a-4409-9a51-600cf115ff4a",
    "traceEventsPath": "/v1/query/4576b626-c27a-4409-9a51-600cf115ff4a/events",
    "route": "rag",
    "correctedQuery": "What are our retention rules?",
    "evidenceStatus": "sufficient",
    "abstained": false,
    "claims": [],
    "citations": [],
    "stages": []
  }
}
```

Response headers:

- `X-Cortex-Contract-Version: v1`
- `X-Cortex-Trace-Id: <trace UUID>`
- `X-Cortex-Evidence-Status: sufficient|partial|insufficient|conflict`

## `x_cortex` fields

- `contractVersion`: stable extension-contract version for replacement query shells
- `traceId`: stable execution identifier for audit, feedback, and developer trace lookup
- `traceEventsPath`: persisted SSE trace path for elevated builder/operator tooling on the same Cortex host
- `route`: `rag`, `compute`, or `retrieve-then-compute`
- `correctedQuery`: spelling-corrected query when Cortex used one materially
- `evidenceStatus`: `sufficient`, `partial`, `insufficient`, or `conflict`
- `abstained`: whether Cortex withheld a fully supported answer
- `claims`: validated atomic claims only
- `citations`: exact evidence spans for validated claims
- `stages`: summarized deterministic execution stages

## Integration guidance

- Treat `choices[0].message.content` as display text.
- Treat `x_cortex.citations` as the source of truth for evidence rendering.
- Treat `x_cortex.evidenceStatus` and `x_cortex.abstained` as answer-governance signals.
- Treat `x_cortex.claims[*].supportStatus` as the atomic support verdict for each claim,
  especially when Cortex returns `partial`, `insufficient`, or `conflict`.
- Store `x_cortex.traceId` with user feedback so operators can reconcile query outcomes in the console.
- Expect `x_cortex.contractVersion === "v1"` before relying on this extension shape.
- Treat `x_cortex.traceEventsPath` as an operator/debug correlation pointer. Do not call it directly from a standard employee-facing replacement UI unless that client is intentionally running with builder-grade identity and permissions.
- Use the returned `traceId` to fetch persisted trace detail from the fixed developer console rather than recreating hidden pipeline state in the client UI.

## Replacement UI checklist

- Authenticate the employee user and forward the bearer token to Cortex.
- Call `POST /v1/chat/completions` with `stream=false`.
- Render `choices[0].message.content` as the answer text.
- Render `x_cortex.citations` and `x_cortex.evidenceStatus` as the evidence boundary.
- Treat `x_cortex.abstained=true` as an intentional no-answer outcome, not a transport failure.
- Persist `x_cortex.traceId` anywhere the client captures user feedback or support tickets.
- Do not depend on direct access to `x_cortex.traceEventsPath` from the employee browser surface.

## Non-goals of this contract

- No arbitrary tool execution
- No client-supplied access scope
- No dynamic code execution
- No token-by-token answer streaming on this facade
