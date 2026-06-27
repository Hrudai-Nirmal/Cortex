# External Query Contract

## Purpose

Cortex ships a bundled `query-web` surface, but enterprise clients may replace it with
their own chat shell. The supported integration boundary for those clients is:

- `POST /v1/chat/completions`
- `GET /v1/chat/contracts/v1`

This route is intentionally OpenAI-compatible enough for standard chat UIs while adding
the Cortex evidence metadata a governed RAG system needs.

Contract stability rules:

- The OpenAI-style response envelope remains the compatibility baseline.
- Cortex-specific behavior is additive through `x_cortex` fields and `X-Cortex-*` headers.
- Replacement UIs should gate feature assumptions on `contractVersion === "v1"`.
- Trace replay remains an elevated operator/debug capability even when the query UI is fully replaced.
- `GET /v1/chat/contracts/v1` is the machine-readable discovery endpoint for the live `v1` contract.

## Live discovery

The running Cortex package exposes `GET /v1/chat/contracts/v1` as a machine-readable
descriptor for the replacement-query contract. It publishes:

- `contractVersion`
- `endpointPath`
- `method`
- `authentication`
- `supportsStreaming`
- `requestOptions`
- `querySurfaceMode`
- `bundledQueryUiAvailable`
- `traceEventsPathTemplate`
- `operatorConsolePath`
- `responseHeaders`
- `extensionFields`
- `employeeSafeExtensionFields`
- `operatorOnlyExtensionFields`
- `errorStatuses`
- `evidenceStatuses`
- `routes`
- `abstentionEvidenceStatuses`
- `notes`

Replacement query shells may cache this descriptor at startup to confirm they are
integrating with a compatible Cortex deployment before issuing real user queries.
The shipped `query-web` surface now does exactly this, which keeps the bundled employee UI
honest as one more consumer of the public contract rather than a bypass around it.
`pnpm package:verify` now checks the same live descriptor semantics at the package boundary, so
operators can prove the shipped deployment still advertises the full replacement-query contract.

The descriptor now also formalizes the split between what an employee-facing UI may depend
on and what should remain reserved for elevated debugging:

- `requestOptions` documents the stable request semantics replacement UIs must follow.
- `querySurfaceMode` tells clients whether Cortex currently ships the bundled employee shell
  or exposes the query host as an API-only contract for a client-owned UI.
- `bundledQueryUiAvailable` is the matching capability flag for gateways or SDK layers that
  prefer a direct boolean instead of interpreting the surface-mode enum.
- `employeeSafeExtensionFields` identifies the `x_cortex` fields a standard employee UI may
  safely use.
- `operatorOnlyExtensionFields` identifies fields that should remain correlation/debug aids.
- `errorStatuses` publishes the stable non-abstention error meanings a replacement UI should
  distinguish from a successful answer contract.
- `responseHeaders`, `evidenceStatuses`, `routes`, and `abstentionEvidenceStatuses` are also part
  of the live semantic contract and should be validated before trusting the deployed package.

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
- The live discovery descriptor always points back to this request shape through `endpointPath` and `method`.
- Replacement UIs should also verify `querySurfaceMode` and `bundledQueryUiAvailable` so they
  know whether they are replacing the employee shell or running alongside the shipped one.
- The bundled `query-web` surface now validates the response headers (`X-Cortex-*`) against the
  `x_cortex` payload so contract drift is detected early.
- Replacement UIs should also validate `requestOptions` before enabling traffic so they fail
  closed if the deployment no longer guarantees `stream=false`, the last-user-message
  selection rule, or the citation toggle contract they expect.
- Replacement UIs should also validate `responseHeaders`, `evidenceStatuses`, `routes`,
  `abstentionEvidenceStatuses`, and `errorStatuses` so semantic contract drift fails closed
  before employee traffic starts flowing.

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
- `X-Cortex-Route: rag|compute|retrieve-then-compute`
- `X-Cortex-Abstained: true|false`

Stable error meanings advertised through `errorStatuses`:

- `422 invalid_request`: the request shape violates the stable Cortex facade, such as `stream=true`
  or no usable user message
- `403 forbidden_scope`: the authenticated identity is not allowed to access the requested
  enterprise scope or sources
- `503 provider_unavailable`: a required local provider was unavailable or timed out during
  deterministic execution
- `500 internal_error`: Cortex failed outside the expected validation, authorization, or
  provider error contract

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

## Response interpretation

- `choices[0].message.content` is always the displayable answer text, including abstentions.
- `x_cortex.evidenceStatus` is the evidence verdict, not a transport verdict.
- `x_cortex.abstained=true` means Cortex intentionally withheld a fully supported answer.
- `X-Cortex-Abstained` duplicates that abstention signal in header form for gateways, observability, and thin clients that inspect headers before parsing the JSON body.
- `X-Cortex-Route` exposes whether Cortex answered through RAG, deterministic compute, or retrieve-then-compute so operators can reconcile runtime behavior without inferring it from answer text.
- `x_cortex.claims` and `x_cortex.citations` remain the source of truth for claim-level evidence rendering.
- `employeeSafeExtensionFields` is the allowlist a replacement employee UI should treat as its
  supported dependency boundary.
- `operatorOnlyExtensionFields` marks fields such as `traceEventsPath` that should not become a
  hard dependency of a standard employee browser shell.

## Error contract

- `422` means the request shape is invalid for the stable facade, for example:
  - empty final user query
  - no `user` message
  - `stream=true`
- `403` means Cortex rejected the request because the authenticated identity or scope was not allowed.
- `503` means a required local provider, most commonly the bounded generation model call, was unavailable or timed out while Cortex was executing the deterministic pipeline.
- `500` means Cortex itself failed outside the expected domain/provider error contract.

Replacement UIs should distinguish these cases from intentional abstention. Abstention is represented as a successful `200` response with evidence metadata, not as an exception path.

## Integration guidance

- Treat `choices[0].message.content` as display text.
- Read and validate `requestOptions` before sending traffic from a replacement UI.
- Read and validate the descriptor’s `responseHeaders`, `evidenceStatuses`, `routes`,
  `abstentionEvidenceStatuses`, and `errorStatuses` before enabling traffic from a replacement UI.
- Treat `x_cortex.citations` as the source of truth for evidence rendering.
- Treat `x_cortex.evidenceStatus` and `x_cortex.abstained` as answer-governance signals.
- Treat `x_cortex.claims[*].supportStatus` as the atomic support verdict for each claim,
  especially when Cortex returns `partial`, `insufficient`, or `conflict`.
- Store `x_cortex.traceId` with user feedback so operators can reconcile query outcomes in the console.
- Expect `x_cortex.contractVersion === "v1"` before relying on this extension shape.
- Treat `x_cortex.traceEventsPath` as an operator/debug correlation pointer. Do not call it directly from a standard employee-facing replacement UI unless that client is intentionally running with builder-grade identity and permissions.
- Use the returned `traceId` to fetch persisted trace detail from the fixed developer console rather than recreating hidden pipeline state in the client UI.
- Distinguish intentional abstention from `errorStatuses`; abstention remains a successful `200`
  response with evidence metadata rather than an exception path.

## Replacement UI checklist

- Authenticate the employee user and forward the bearer token to Cortex.
- Validate `requestOptions.streamRequiredValue === false` and
  `requestOptions.userMessageSelectionPolicy === "last-non-empty-user-message"` at startup.
- Call `POST /v1/chat/completions` with `stream=false`.
- Render `choices[0].message.content` as the answer text.
- Render `x_cortex.citations` and `x_cortex.evidenceStatus` as the evidence boundary.
- Treat `x_cortex.abstained=true` as an intentional no-answer outcome, not a transport failure.
- Persist `x_cortex.traceId` anywhere the client captures user feedback or support tickets.
- Preserve `X-Cortex-Route` and `X-Cortex-Abstained` in gateway or observability logs if the client stack records response headers.
- Treat `employeeSafeExtensionFields` as the safe UI dependency boundary for the employee shell.
- Do not depend on direct access to `x_cortex.traceEventsPath` from the employee browser surface.

## Non-goals of this contract

- No arbitrary tool execution
- No client-supplied access scope
- No dynamic code execution
- No token-by-token answer streaming on this facade
