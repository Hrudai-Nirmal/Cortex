# Cortex

Cortex is an offline-capable, evidence-bounded RAG pipeline builder for dedicated enterprise deployments. It separates a graph-first developer console from a focused employee query experience while sharing the same authorization, provenance, citation, and audit controls.

## Shipping model

Cortex is packaged as a multi-image container bundle:

- `api`
- `worker`
- `console-web`
- `query-web`
- `edge` (Nginx host router)

The console and built-in query UI are independent frontend images. They are routed by
host, not by path, so client deployments can use domains such as:

- `cortex-console.company.com`
- `cortex-app.company.com`

Those browser images now take their public console/query URLs from runtime container
environment, so the same packaged `console-web` and `query-web` images can be promoted
across client domains without rebuilding just to retarget cross-surface navigation.

The built-in query UI remains optional and replaceable. The console is the default
operator surface and is not intended to be swapped out.

The bundled query UI now treats `sufficient`, `partial`, `insufficient`, and `conflict`
evidence states differently so client-owned chat shells have a trustworthy reference
consumer for the external contract.
It also reads `GET /v1/chat/contracts/v1` at startup and validates the response headers
and `x_cortex` fields it depends on, so it behaves like a real contract consumer rather
than a privileged in-repo special case.

## External query contract

Client-owned chat shells should integrate through `POST /v1/chat/completions`.
This OpenAI-compatible facade derives access scope from the authenticated bearer token,
so replacement UIs do not send raw ACL principals from the browser. Cortex returns the
assistant message in the standard `choices` envelope and adds `x_cortex` metadata with:

- `contractVersion`
- `traceId`
- `traceEventsPath` for elevated operator/debug tooling
- `route`
- `correctedQuery`
- `evidenceStatus`
- `abstained`
- validated `claims`
- exact `citations`
- stage summaries

The response headers also carry:

- `X-Cortex-Contract-Version`
- `X-Cortex-Trace-Id`
- `X-Cortex-Evidence-Status`
- `X-Cortex-Route`
- `X-Cortex-Abstained`

The live package also publishes `GET /v1/chat/contracts/v1` so operators and replacement
UI builders can discover the exact stable contract metadata from the running deployment.
That descriptor now also states whether the deployment ships the bundled employee shell
(`querySurfaceMode=bundled`, `bundledQueryUiAvailable=true`) or exposes the query host as
an API-only contract for a client-owned chat UI (`querySurfaceMode=external`,
`bundledQueryUiAvailable=false`).
That live descriptor now also publishes the stable request semantics, employee-safe versus
operator-only `x_cortex` fields, and machine-readable error meanings so third-party chat
shells can integrate against the running package without reverse-engineering the bundled UI.
The bundled `query-web` surface and `pnpm package:verify` now also validate the live
response-header set, evidence-status enums, route enums, abstention enums, and required
error meanings, and the bundled employee shell now refuses to run against an API-only
`querySurfaceMode=external` deployment contract, so Cortex treats its own shipped UI and package tooling as strict
consumers of that same replacement-query contract.

See [external-query-contract.md](docs/external-query-contract.md) for the stable wire contract.

## Development

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ingestion]'
pnpm --dir apps/web install
pnpm dev:up
pnpm dev:seed
```

The local split surfaces run at:

- console: `http://127.0.0.1:5173`
- app: `http://127.0.0.1:5174`
- API: `http://127.0.0.1:8000`

`pnpm dev:up` starts PostgreSQL and Ollama through Docker Compose, applies migrations,
and launches the API, worker, console, and app surfaces as local background processes.
`pnpm dev:seed` loads the deterministic integration fixture set.

## Source onboarding

- Developer source operations live in the console surface on the console host in the `Sources` and `Jobs` tabs.
- The console now exposes persisted source hashes, extraction diagnostics, accelerator reports, and focused durable job detail for operator troubleshooting.
- The source-detail lane now surfaces per-document version counts, active vs failed/quarantined history, the stable source fingerprint, and retrieval-status guidance that distinguishes the newest onboarded version from the version that is actually live for retrieval.
- The console version lane now distinguishes active, validated, and retired immutable pipeline versions so operators can see promotable releases and explicit rollback targets.
- The console version lane now also builds a lifecycle queue for active, validated, and retired releases so promotion and rollback start from explicit operator actions instead of only a version table.
- The console trace lane now shows validated answer preview, claim support status, citation linkage, and stage evidence together for faster operator review.
- The console trace lane now also exposes ranked retrieved evidence rows so operators can inspect which source chunks actually drove a response without leaving the fixed console.
- The console settings lane now surfaces the packaged model profile and identity profile directly, not only as rows in the readiness table.
- The console settings lane now reads the live external query contract descriptor so operators can verify the exact third-party chat integration boundary from the running package.
- The console settings lane now also separates the fail-closed startup contract from live runtime readiness, so operators can distinguish static package boot blockers from live dependency regressions without leaving the fixed console.
- The console settings lane now also builds an operator action queue from startup blockers, runtime degradations, and surface-contract failures so deployment troubleshooting starts with an explicit fix list instead of a table hunt.
- The source operations lane now also builds an operator queue for failed, quarantined, processing, and stale-live-version onboarding states so source triage starts with actions instead of raw diagnostics.
- The selected source-detail and job-detail panes now keep polling their persisted records while the lists refresh, so operators see activation/failure transitions in place instead of opening a stale detail view and waiting for a manual reselection.
- Supported source formats: PDF, DOCX, HTML, TXT/Markdown, and CSV.
- Uploads are stored once by raw SHA-256 beneath `CORTEX_OBJECT_STORAGE_ROOT`, then ingested through durable jobs.
- Single-page website ingestion is restricted to `CORTEX_WEBSITE_ALLOWLIST`.
- macOS development profiles still fail closed if Docling OCR falls back from MPS to CPU.

## Profiles

- `development-macos`: requires MPS for accelerated Docling model stages and fails closed on an unexpected CPU fallback.
- `development-cpu`: explicit CPU profile for CI or machines without Metal.
- `production`: requires the operator to select the expected accelerator and model artifacts.

## Packaging

`docker-compose.package.yml` demonstrates the shippable container bundle with host-based
Nginx routing. `infra/k8s/cortex-package.yaml` provides a generic ingress-based layout
for Kubernetes platforms such as EKS, AKS, GKE, OpenShift, and RKE2.

The Kubernetes package example uses placeholder client domains (`cortex-console.example.com`
and `cortex-app.example.com`), a `cortex-config` ConfigMap for non-secret runtime
settings, `cortex-secrets` for deployment-specific secrets, and a persistent volume
claim for `/var/lib/cortex/object-storage`.

The package now includes:

- `GET /health/live` for liveness
- `GET /health/startup` for static deployment validation
- `GET /health/ready` for database, pgvector, model, storage, and accelerator readiness
- runtime-health payloads with per-component severity and remediation guidance for operators
- runtime-health payloads that explicitly declare the packaged generator, embedding, and accelerator profile
- runtime-health payloads that explicitly declare the packaged Torch wheel/build profile used for Docling-backed container images
- runtime-health payloads that explicitly declare the packaged identity profile, including auth mode and OIDC contract
- container and ingress examples with readiness/liveness probes
- explicit host/public URL configuration for both browser surfaces
- production public-surface validation that rejects HTTP browser URLs, nested-path public URLs, and unmodified `example.com` placeholder hosts before the package boots
- explicit packaged model-profile declaration for generator, embeddings, and accelerator expectations
- explicit packaged production-profile declaration so client bundles do not inherit development-mode defaults
- an offline-capable model-endpoint policy check that flags unexpected remote model hosts
- a startup object-storage read/write probe so mis-mounted persistent volumes fail with a precise operator message instead of a later ingestion surprise
- runtime health warns when the package is still using fixture auth so operators do not confuse evaluation identity with a real client auth rollout
- package verification that checks split-surface identity headers, both routed health views, and query-contract identity headers
- package verification now also checks the startup-health `deployment-config` detail for
  the shipped console/query public URLs, fail-closed startup policy, and declared
  query-surface mode instead of only trusting a generic `ready` status
- package verification that checks the browser `cortex-runtime-config.js` payload on both hosts so frontend runtime config matches the deployed client domains
- package verification that now fails with named operator-readable routing, contract, runtime-config, and worker-startup errors instead of opaque shell `grep` exits
- browser runtime-config delivery that serves `cortex-runtime-config.js` with `Cache-Control: no-store, no-cache, must-revalidate` so client-domain changes take effect immediately after a rollout instead of lingering in browser caches
- package verification that also runs the worker startup check so durable job readiness is proven alongside API/browser readiness
- package verification that checks query-contract route and abstention headers so third-party chat shells can rely on the packaged facade behavior
- package bootstrap/status now prove both routed browser hosts resolve to the expected Cortex surfaces before operators treat the package as healthy
- package bootstrap now also proves both routed browser hosts publish the expected `cortex-runtime-config.js` values and no-store cache policy before declaring the package healthy
- package bootstrap/status now also show whether the worker startup check passes, so operators can distinguish “UI/API look healthy” from “safe to process jobs”
- shipped Kubernetes and ECS package examples now pin `CORTEX_QUERY_SURFACE_MODE`
  explicitly so bundled versus client-owned employee shells cannot drift through backend
  defaults
- API and worker settings loading now collapse invalid deployment env into one
  operator-readable `invalid Cortex settings: ...` error instead of a raw validation dump
- package status now prints the live query-contract version, route set, abstention evidence states, response headers, request semantics, employee-safe versus operator-only `x_cortex` fields, and stable error meanings from `GET /v1/chat/contracts/v1`
- package status now also prints the live startup deployment contract summary for the
  shipped console/query public URLs, fail-closed startup policy, and query-surface mode
- package status now prints the browser runtime-config public URLs exposed by both frontend hosts so operators can catch split-host drift without opening dev tools
- frontend surface config that keeps localhost defaults for development but rejects missing, placeholder, localhost, non-HTTPS, or nested-path public URLs inside packaged production browser builds
- frontend runtime-config injection that reads `CORTEX_CONSOLE_PUBLIC_URL` and `CORTEX_QUERY_PUBLIC_URL` at container startup so browser-surface links stay aligned with the deployed client domains
- fixed-console cross-surface navigation that prefers the runtime deployment contract from `GET /health/startup`, so the “Open employee view” link follows the live packaged query host instead of stale local browser assumptions when package state drifts
- fixed-console release-gate checklist that collapses startup health, live dependencies,
  active immutable pipeline state, external query-contract availability, queued validated
  versions, and latest trace evidence into one operator go-live view
- OpenShift Route and ECS task-family examples for client-owned split-host deployments, including a one-shot ECS migration task
- an additional ECS task-family example for client-owned query UIs that keeps the fixed console, API, and worker while leaving the employee chat shell outside the Cortex package
- additional Kubernetes and OpenShift external-query examples that keep the fixed console, API, and worker while leaving the employee chat shell outside the Cortex package
- an explicit `CORTEX_QUERY_SURFACE_MODE` package switch plus a dedicated `docker-compose.package.external-query.yml` flow so operators can boot the fixed console/API/worker bundle without pretending the client-owned employee chat shell is still shipped inside Cortex
- operator scripts:
  - `pnpm package:up`
  - `pnpm package:status`
  - `pnpm package:logs`
  - `pnpm package:pull-models`
  - `pnpm package:verify`
  - `pnpm package:down`

The shipped local package profile also defaults the Docling/Torch build path to the CPU
PyTorch wheel channel (`CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL=https://download.pytorch.org/whl/cpu`)
so Docker Desktop verification does not accidentally pull CUDA-heavy Linux wheels. For an
intentional NVIDIA client build, set that variable to the matching PyTorch CUDA wheel
channel before rebuilding the `api`, `worker`, and `migrate` package images.

The worker now validates both startup-safe configuration and live dependency readiness
before it enters its durable job loop, so broken package deployments fail fast instead
of quietly polling forever.

The API now applies the same fail-closed startup policy for packaged production profiles:
if static startup health is degraded, the process logs the failing components and exits
instead of serving a partially valid client package.

The worker now also exposes an explicit `python -m cortex.worker --check-startup` probe
contract, and the shipped Compose/Kubernetes/ECS manifests use it so client-managed
orchestrators can tell “safe to process jobs” from “container merely started.”

`pnpm package:up` now prints the exact degraded startup/readiness components and their
remediation instead of failing with a generic timeout when package validation disagrees
with the deployment profile.

It also fails fast when operators leave the documentation placeholder domains in place,
configure non-HTTPS public browser URLs, append a path to a public surface URL, point
the model endpoint at a public host without explicitly allowing that dependency, or use
a non-absolute object-storage mount path.

When the package still cannot become healthy, `pnpm package:up` now prints the current
Compose service state plus recent `api`, `worker`, and `edge` logs so operators are not
left guessing whether the failure happened in static config, API startup, or the routed edge.

See [context.md](context.md), [architecture.md](docs/architecture.md),
[external-query-contract.md](docs/external-query-contract.md),
[operator-runbook.md](docs/operator-runbook.md),
[split-frontend-packaging.md](docs/split-frontend-packaging.md), and
[threat-model.md](docs/threat-model.md).
