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
- The source-detail lane now also surfaces active/failed/quarantined version counts plus the currently active version label so operators can tell whether the latest onboarding attempt actually changed the live corpus.
- The developer console now distinguishes validated pipeline versions from the active release and exposes retired immutable versions as explicit rollback targets.
- The developer console trace view now includes validated answer preview plus persisted claims, support status, and citation linkage instead of only stage counts and citation totals.
- The developer console trace view now also exposes persisted retrieved-evidence rows with source, locator, and ranking scores so operators can inspect the actual chunks behind a response.
- The developer console settings view now foregrounds packaged model and identity profiles so operators can confirm deployment intent without scanning the raw readiness table.
- Multi-image frontend packaging with separate console/query Vite builds, static frontend Docker images, edge Nginx host routing, and package/Kubernetes deployment manifests.
- The Kubernetes package example now models client-owned domains, shared non-secret config, secret injection, and persistent object storage instead of baking in development hostnames.
- External query-surface contract through an OpenAI-compatible `/v1/chat/completions` facade that derives access scope from authenticated identity and returns `x_cortex` evidence metadata, a stable contract version, an operator-oriented trace-events path, and trace-oriented response headers.
- The live package now also publishes a machine-readable `GET /v1/chat/contracts/v1` descriptor so replacement client chat UIs and operators can verify the exact stable `v1` integration contract from the running deployment.
- The external query facade now also emits explicit route and abstention response headers so thin clients, gateways, and operator observability can integrate without reverse-engineering the JSON payload.
- Source onboarding and source operations: multipart file uploads, allowlisted single-page website snapshots, blob deduplication by raw SHA-256, pending/failed/active source versions, durable source ingestion jobs, and developer-side source/job views.
- Governance foundation: fixture-compatible bearer/OIDC identity resolution, `/v1/session`, developer-side builder/admin RBAC, audit-backed permission denials, persisted pipeline governance endpoints, and authenticated source/pipeline operations that derive actor identity server-side.
- Deployment hardening: validated split-host/public-URL settings, startup/readiness health endpoints, model-endpoint offline policy checks, pgvector readiness checks, container health probes, and operator-facing package docs.
- Deployment hardening: validated split-host/public-URL settings, explicit packaged production/model-profile declarations, startup/readiness health endpoints, model-endpoint offline policy checks, pgvector readiness checks, container health probes, and operator-facing package docs.
- Runtime health now carries severity and remediation guidance across API responses, package scripts, and the fixed developer console; the worker refuses to enter its loop when startup or live readiness checks fail.
- Runtime health now carries severity and remediation guidance across API responses, package scripts, and the fixed developer console; it also declares the packaged generator/embedding/accelerator profile plus the active auth/OIDC profile so operators can verify deployment intent before deeper debugging, warns when a packaged deployment is still using fixture auth, and the worker refuses to enter its loop when startup or live readiness checks fail.
- Operator bootstrap tooling: `.env.package.example`, package up/verify/down scripts, and a deployment runbook for Docker, Kubernetes, OpenShift, and ECS-style host routing.
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
