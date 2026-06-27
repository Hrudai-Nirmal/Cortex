# Cortex Context

## Product
Cortex builds tailored, dedicated-per-client RAG deployments. Within each enterprise, RBAC controls actions and document ACL principals are mandatory SQL predicates for retrieval. The first development profile targets at most 30,000 active chunks on a 64 GB Apple Silicon Mac.

## Current Architecture
- FastAPI/Python modular monolith with separate worker entry points.
- PostgreSQL, pgvector, full-text search, and a PostgreSQL job table.
- React/TypeScript/Vite web application with React Flow.
- Split frontend packaging: dedicated console build, dedicated query-app build, and Nginx host-based routing.
- Developer surface: graph-first pipeline operations and trace inspection.
- End-user surface: friendly query UI with optional citation display, but packaged as a replaceable app surface.
- The bundled query surface now renders `sufficient`, `partial`, `insufficient`, and `conflict` evidence outcomes distinctly instead of treating every response as fully supported.
- The bundled query surface now also discovers the live `v1` query contract at startup and validates the `X-Cortex-*` headers plus required `x_cortex` response fields it depends on, so it behaves like a real external contract consumer.
- The bundled query surface now also refuses to run against `querySurfaceMode=external`
  / `bundledQueryUiAvailable=false` deployments and rejects semantic response drift in
  route/evidence-status/abstention consistency, so the shipped employee shell behaves
  like a strict consumer of the same public contract client-owned UIs must follow.
- Provider interfaces isolate parsing, embedding, reranking, generation, storage, and identity.

## Implemented Vertical Slice
- Initial PostgreSQL/pgvector migration, including deterministic binary chunk keys, active-version indexes, typed memories, durable jobs, and trace/audit retention.
- Retry-safe in-memory and PostgreSQL ingestion repositories with batch checkpoints and transactional activation.
- Strict MPS accelerator guard and offline Docling adapter boundary.
- Scoped lexical/vector SQL, RRF truncation, typed computation registry, persisted query service, SSE stage events replayed from trace storage, and generated OpenAPI browser contracts.
- Durable PostgreSQL job queue with worker-side ingestion and retention handlers.
- Deterministic seed fixtures covering multi-tenant scope, ACL differences, version activation, freshness conflicts, and retrieve-then-compute examples.
- React Flow developer console plus a separate friendly employee query surface with citation display control, live pipeline/health fetches, and persisted trace playback.
- The developer console now surfaces focused durable-job detail plus persisted source hashes, extraction diagnostics, and accelerator reports for operator troubleshooting.
- The source-detail lane now also surfaces active/failed/quarantined version counts, the stable source fingerprint, and retrieval-status guidance that tells operators whether the newest onboarding attempt is actually retrievable or whether an older active version still serves the live corpus.
- The developer console now distinguishes validated pipeline versions from the active release and exposes retired immutable versions as explicit rollback targets.
- The developer console versions lane now also builds a lifecycle queue from active, validated, and retired pipeline versions, so promotion and rollback intent show up as operator actions instead of only release rows.
- The developer console trace view now includes validated answer preview plus persisted claims, support status, and citation linkage instead of only stage counts and citation totals.
- The developer console trace view now also exposes persisted retrieved-evidence rows with source, locator, and ranking scores so operators can inspect the actual chunks behind a response.
- The developer console settings view now foregrounds packaged model and identity profiles so operators can confirm deployment intent without scanning the raw readiness table.
- The developer console now tolerates partial settings-side API failures instead of blanking the whole surface, and its settings lane adds a first-class surface-deployment contract summary for split-host isolation, startup policy, and live query-contract availability.
- The developer console settings lane now also consumes both `GET /health/startup` and `GET /health/ready`, separating fail-closed package boot checks from live runtime dependency drift so operators can tell “won’t boot” from “booted but degraded” inside the fixed console.
- The developer console settings lane now also builds an operator action queue from startup blockers, live runtime degradations, and degraded surface-contract checks, so deployment troubleshooting starts with a prioritized fix list instead of requiring operators to scan every table manually.
- The developer console source-operations lane now also builds an operator queue from failed, quarantined, processing, and stale-live-version conditions, so source onboarding drift is visible as actions instead of only raw version metadata.
- Multi-image frontend packaging with separate console/query Vite builds, static frontend Docker images, edge Nginx host routing, and package/Kubernetes deployment manifests.
- The Kubernetes package example now models client-owned domains, shared non-secret config, secret injection, and persistent object storage instead of baking in development hostnames.
- External query-surface contract through an OpenAI-compatible `/v1/chat/completions` facade that derives access scope from authenticated identity and returns `x_cortex` evidence metadata, a stable contract version, an operator-oriented trace-events path, and trace-oriented response headers.
- The live package now also publishes a machine-readable `GET /v1/chat/contracts/v1` descriptor so replacement client chat UIs and operators can verify the exact stable `v1` integration contract from the running deployment, including request semantics, employee-safe versus operator-only `x_cortex` fields, and stable non-abstention error meanings.
- That live descriptor now also exposes `querySurfaceMode` plus `bundledQueryUiAvailable`, so operators and client UI integrators can verify whether the current package actually ships the employee query shell or exposes the query host as an API-only contract for a client-owned UI.
- The bundled query surface and `package:verify` now also reject semantic contract drift in that descriptor, including missing response headers, evidence-status enums, route enums, abstention-status enums, and required machine-readable error codes, so the shipped package keeps acting like a strict third-party integration target.
- The external query facade now also emits explicit route and abstention response headers so thin clients, gateways, and operator observability can integrate without reverse-engineering the JSON payload.
- Source onboarding and source operations: multipart file uploads, allowlisted single-page website snapshots, blob deduplication by raw SHA-256, pending/failed/active source versions, durable source ingestion jobs, and developer-side source/job views.
- Governance foundation: fixture-compatible bearer/OIDC identity resolution, `/v1/session`, developer-side builder/admin RBAC, audit-backed permission denials, persisted pipeline governance endpoints, and authenticated source/pipeline operations that derive actor identity server-side.
- Deployment hardening: validated split-host/public-URL settings, startup/readiness health endpoints, model-endpoint offline policy checks, pgvector readiness checks, container health probes, and operator-facing package docs.
- Deployment hardening: validated split-host/public-URL settings, explicit packaged production/model-profile declarations, startup/readiness health endpoints, model-endpoint offline policy checks, pgvector readiness checks, container health probes, and operator-facing package docs.
- Runtime health now carries severity and remediation guidance across API responses, package scripts, and the fixed developer console; the worker refuses to enter its loop when startup or live readiness checks fail.
- Runtime health now carries severity and remediation guidance across API responses, package scripts, and the fixed developer console; it also declares the packaged generator/embedding/accelerator profile plus the active auth/OIDC profile so operators can verify deployment intent before deeper debugging, warns when a packaged deployment is still using fixture auth, and the worker refuses to enter its loop when startup or live readiness checks fail.
- Operator bootstrap tooling: `.env.package.example`, package up/verify/down scripts, and a deployment runbook for Docker, Kubernetes, OpenShift, and ECS-style host routing.
- The shipped ECS examples now include both the full split-host package and an API-only external-query variant, so client-owned chat shells have a concrete deployment artifact instead of only prose guidance.
- The shipped Kubernetes and OpenShift examples now also include API-only external-query variants, so client-owned chat shells have concrete non-ECS deployment artifacts instead of only a general recommendation.
- The local package workflow now mirrors that same split: `CORTEX_QUERY_SURFACE_MODE=bundled|external` selects between the full split-host bundle and a dedicated `docker-compose.package.external-query.yml` package that omits `query-web` while preserving the fixed console, API/worker, and query-host contract surface.
- Package operator scripts now also fail fast with a clear message when Docker is installed but its daemon/runtime is unavailable, so local client-package debugging does not start with raw socket errors.
- `package:pull-models` now also fails fast when the deployment is intentionally configured for a remote model endpoint, so operators do not mistakenly preload the bundled local Ollama while the real runtime points somewhere else.
- The local packaged verification profile now defaults to a CPU-friendly `qwen3:1.7b` generator plus `qwen3-embedding:0.6b`, while heavier production profiles remain operator-configurable per client deployment.
- Operator inspection tooling: package status/log-tail scripts, split-host surface identity checks during bootstrap/status, and clearer runtime alert surfacing inside the fixed developer console.
- Package verification now asserts split-surface identity headers plus query-contract version and trace-events metadata, while the console trace panel exposes actor, start time, and stage count for the latest run.
- Package verification now asserts split-surface identity headers plus `live`/`startup`/`ready` health responses through both browser hosts, alongside query-contract version and trace-events metadata.
- Packaged verification now avoids slow trace seeding on `/v1/dev/seed`, and the edge router grants `/v1/` requests a 300-second timeout window so cold local-model responses do not fail behind Nginx.
- The shippable package now forces an explicit PyTorch wheel channel for Docling-backed images, defaulting local packaged verification to CPU-only Torch artifacts instead of accidental CUDA-heavy Linux downloads; operators can override that build-time channel explicitly for intentional NVIDIA deployments.
- Route-level error handling now preserves domain failure meaning: provider/model failures surface as `503` instead of being masked by the database-session dependency, and bounded generation now gets a longer provider timeout aligned with the packaged edge proxy window.
- Runtime health and the fixed developer console now expose a first-class `package-build-profile` component so operators can inspect the packaged Torch wheel channel and preinstalled model-runtime packages from the running deployment, and the shipped Kubernetes/ECS examples now carry the same declared build-profile settings.
- The query service now prefers a deterministic extractive claim path when a strong top-scoped chunk already answers the question, which keeps citation-backed packaged verification fast and avoids unnecessary local structured-generation round-trips on straightforward evidence lookups.
- Packaged local verification now completes end to end against live PostgreSQL, Ollama, worker, and split-host routing by using a CPU-friendly local model profile plus shorter bounded-claim generation tuned for deterministic citation-backed answers.
- The generated TypeScript API contract is now re-synced with the live FastAPI OpenAPI schema and guarded by tests so the external chat facade metadata cannot silently drift from the browser clients.
- Package startup now reports degraded startup/readiness components with remediation instead of generic timeouts, and the package artifacts now include corrected OpenShift Route examples plus ECS runtime and migration task examples for split-host client deployments.
- Package runtime validation now rejects documentation placeholder domains, non-HTTPS production browser URLs, nested-path public URLs, and relative production object-storage roots before client packages boot.
- Package bootstrap now includes an explicit migration step and an operator model-pull step for Ollama-backed local deployments.
- Runtime object-storage readiness now performs an explicit write/delete probe, and `package:status` prints the live external query-contract summary from the running query host.
- The packaged API now applies the same fail-closed startup policy as the worker for degraded static startup health, while development profiles remain report-only for debugging.
- Package bootstrap now prints Compose service state plus recent `api`/`worker`/`edge` logs when startup still fails after boot, which makes direct client-package debugging much less opaque.
- The worker now also exposes a dedicated `--check-startup` probe path, and the shipped Compose/Kubernetes/ECS manifests use it so orchestrators can gate durable job execution on real runtime readiness instead of process existence alone.
- Package operator tooling now also runs and reports that worker startup-check contract directly during `package:up`, `package:status`, and `package:verify`, so packaged job safety is visible alongside split-host/API readiness.
- Durable job detail now exposes its persisted `updatedAt` timestamp through the API contract so the developer jobs lane can render a truthful last-updated value without type drift.
- The browser surfaces now validate their own packaged Vite public-URL and surface env at runtime, keeping development localhost defaults for local work but rejecting missing, localhost, placeholder, non-HTTPS, or nested-path public URLs in production builds before client operators follow a bad cross-surface link.
- The browser images now generate a runtime `cortex-runtime-config.js` from `CORTEX_CONSOLE_PUBLIC_URL` and `CORTEX_QUERY_PUBLIC_URL` when the container starts, so split-host client domains can change without rebuilding `console-web` or `query-web`.
- The fixed console navigation now prefers the runtime `deployment-config` public query URL from `GET /health/startup` over baked frontend assumptions, so operator links continue to target the right employee host when package/browser images and deployment env drift.
- Package operator tooling now also inspects the frontend `cortex-runtime-config.js` payload on both hosts, so `package:status` and `package:verify` can catch browser-runtime split-host drift directly instead of inferring it only from API health.
- Package bootstrap now checks that same `cortex-runtime-config.js` payload and no-store cache policy before declaring the client package healthy, so broken browser-surface env injection fails during `package:up` instead of after operators open the UI.
- Package operator tooling now also treats `GET /v1/chat/contracts/v1` as a richer deployment boundary: `package:verify` asserts the live request semantics, employee-safe versus operator-only field split, and stable machine-readable error meanings, while `package:status` prints those same contract details for operators without making them inspect raw JSON.
- `package:status` now degrades gracefully when the live query-contract endpoint is unavailable, so operators still get the rest of the split-host/runtime summary instead of losing the entire status view to one missing dependency.
- `package:status` now also lifts the startup-health `deployment-config` detail into a
  first-class deployment-contract summary for console/query public URLs, fail-closed
  startup policy, and query-surface mode, so operators do not have to scan raw
  component rows to confirm what package contract is live.
- `package:verify` now labels split-host, runtime-config, worker-startup, and query-contract failures with explicit operator-readable descriptions and points operators back to `pnpm package:status`, so packaged contract drift no longer dies behind an unlabeled `grep` failure.
- `package:verify` now also asserts the live startup-health `deployment-config` detail
  matches the shipped console/query public URLs, fail-closed startup policy, and
  declared query-surface mode, so package readiness cannot drift behind a generic green
  health status.
- The package scripts now keep those same query-contract checks active even when the employee chat shell is client-owned: in `external` query-surface mode they skip bundled `query-web` HTML/runtime-config assertions, switch the edge proxy to the API-only template, and report `external-query-ui (not bundled)` so operators can tell intentional surface omission from an actual packaging failure.
- The fixed console now also falls back to startup-health deployment metadata when the contract endpoint is unavailable, so operators can still see whether the intended query-surface mode is bundled or client-owned during partial outages.
- The shipped Kubernetes and ECS package examples now pin `CORTEX_QUERY_SURFACE_MODE`
  explicitly, preventing client deployments from silently drifting between bundled and
  API-only employee query modes through backend defaults.
- API and worker settings loading now collapse environment validation failures into one
  operator-readable `invalid Cortex settings: ...` runtime error, so packaged bad-env
  boot failures surface clear domain/storage/profile clues instead of raw Pydantic dumps.
- The fixed console Settings tab now includes an operator release-gate checklist that
  combines startup health, live dependencies, active immutable pipeline state, query
  contract availability, queued validated versions, and latest trace evidence into one
  go-live decision view.
- Worker startup now preserves the underlying live-readiness exception text when database/model verification itself crashes, so operators see the real connection/provider clue instead of only a generic readiness failure banner.
- API startup now also preserves the underlying startup-readiness exception text when startup health collection itself crashes, so packaged fail-closed boot errors still surface the real provider/storage/network clue instead of only an unlabeled traceback.
- The packaged browser hosts now serve `cortex-runtime-config.js` with an explicit no-store cache policy, so client-domain changes propagate immediately after rollouts instead of sticking behind cached runtime host mappings.
- Automated domain/security tests, component tests, type checking, production bundling, and optional live PostgreSQL/model integration tests.
- Deployment-health regression coverage now explicitly pins production storage-path validation, remote-model override behavior, object-storage write failures, and accelerator-mismatch reporting.

## Invariants
- Chunk IDs are deterministic SHA-256 digests over canonical, length-delimited inputs.
- Incomplete document versions never participate in retrieval.
- `AccessScope` is required by retrieval APIs and enforced inside SQL.
- RRF output is truncated to a validated 30-50 candidates before reranking; default 40.
- Generated claims must be citation-validated before display.
- Audit metadata outlives raw trace payloads and contains no raw query or answer text.
- On macOS strict development mode, unintended CPU OCR/model execution halts ingestion.
- Source versions are created with raw-hash-backed deterministic identities before parsing, then updated in place with canonical content and parser diagnostics after successful ingestion.
- Quarantined or failed source versions never activate and never participate in retrieval.
- Console and query app are different deployable web images and must not rely on path-based split routing.

## UI Decision
The selected visual target is the first generated direction, “Signal Grid”: a light, dense, graph-first operations console. Employee querying is deliberately a separate, lower-density surface.

## Deferred Boundaries
- Electron may wrap the compiled web application later, but the first release remains browser-first for OIDC and portable deployment.
- The built-in query UI is shippable but optional; enterprise clients may replace it with their own chat shell while preserving Cortex APIs and console.
- Large-scale retrieval engines remain adapters; PostgreSQL/pgvector is the initial implementation.
- Local live-integration verification beyond the unit/component suite still depends on an available PostgreSQL service and local Ollama-compatible model endpoint.
- Malware scanning is still a required hook with a local no-op adapter; enterprise scanner integrations remain a deployment concern rather than a product concern.
- Pipeline validation now clones the latest immutable definition into a distinct validated version when no draft exists; richer draft authoring and explicit evaluated/approved gates remain tied to future pipeline-edit persistence work.
