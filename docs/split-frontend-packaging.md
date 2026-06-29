# Split Frontend Packaging

## Purpose

Cortex ships its developer console and built-in query UI as separate frontend images.
This keeps the operator surface isolated from the employee-facing app and matches
enterprise deployment patterns where clients use distinct domains such as:

- `cortex-console.company.com`
- `cortex-app.company.com`

The query UI remains replaceable. Clients may keep the shipped `query-web` image or
replace it with their own chat shell while continuing to call the Cortex API.
The shipped `query-web` image now reads the live contract descriptor at startup and
validates the `X-Cortex-*` response headers plus required `x_cortex` fields on every
answer, which keeps it aligned with the same public contract client-owned shells use.

## Images

- `cortex/api`
- `cortex/worker`
- `cortex/console-web`
- `cortex/query-web`
- `cortex/edge`

## Routing Model

For container-package deployments outside Kubernetes, the `edge` Nginx image performs
host-based routing:

- console host -> `console-web`
- app host -> `query-web`
- `/v1` and `/health` on both hosts -> `api`

This keeps each browser surface same-origin with the API that it calls while preserving
surface isolation.

When the client keeps its own employee chat UI, set
`CORTEX_QUERY_SURFACE_MODE=external`. The package scripts then switch from
`docker-compose.package.yml` to `docker-compose.package.external-query.yml`, and the
edge proxy uses `infra/nginx/edge.external-query.conf.template` so the console host
still serves the fixed operator UI while the query host exposes only `/v1` and `/health`
for the client-owned chat shell.

For Kubernetes environments such as EKS, AKS, GKE, OpenShift, and RKE2, the same host
split is expressed through ingress rules in `infra/k8s/cortex-package.yaml`.
For clients who keep their own employee chat UI, `infra/k8s/cortex-package-external-query.yaml`
ships the API-only Cortex package mode that preserves `console-web`, `api`, and `worker`
while leaving the query shell outside the package.
Both the bundled and external Kubernetes/ECS examples now declare
`CORTEX_QUERY_SURFACE_MODE` explicitly so the shipped manifests cannot silently inherit
the backend default and drift between bundled versus API-only employee surfaces.

Adjacent platform examples now ship as well:

- `infra/openshift/cortex-package-routes.yaml` maps `/v1` and `/health` to `cortex-api` and `/` to the correct frontend service per host
- `infra/openshift/cortex-package-external-query-routes.yaml` maps the same API paths for both hosts while routing `/` only for the fixed console host when the employee query shell is client-owned
- `infra/ecs/cortex-task-family.json` shows an ECS task-family baseline with split-host environment variables and shared object storage
- `infra/ecs/cortex-migrate-task.json` keeps ECS schema rollout as a separate one-shot task
- `infra/ecs/cortex-task-family-external-query.json` shows the API-only Cortex package mode for client-owned query shells, keeping `console-web`, `api`, and `worker` while leaving the employee chat UI outside the shipped task family

The Kubernetes package example now separates non-secret runtime settings into a
`cortex-config` ConfigMap, expects client-specific secrets through `cortex-secrets`,
and mounts a shared persistent volume for `/var/lib/cortex/object-storage`.

The edge Nginx router emits `X-Cortex-Surface: console|query` so operators can verify
which host resolved to which packaged frontend without relying only on visual inspection.

## Domain Configuration

Domain values are deployment-critical and must be supplied by the operator:

- `CORTEX_CONSOLE_HOST`
- `CORTEX_QUERY_HOST`
- `CORTEX_CONSOLE_PUBLIC_URL`
- `CORTEX_QUERY_PUBLIC_URL`

Model-profile values are also deployment-critical in the packaged flow:

- `CORTEX_ENVIRONMENT=production`
- `CORTEX_DEV_MODE=false`
- `CORTEX_QUERY_SURFACE_MODE=bundled|external`
- `CORTEX_GENERATOR_MODEL`
- `CORTEX_EMBEDDING_MODEL`
- `CORTEX_REQUIRED_ACCELERATOR`
- `CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL`
- `CORTEX_PACKAGE_PYTORCH_PREINSTALL`

Do not hardcode the development domains in client builds.
The package bootstrap now rejects unchanged `example.com` placeholders, and production
browser URLs must remain `https://` origins rooted directly at the host instead of a
nested path such as `/chat` or `/console`.
The browser surfaces now enforce the same expectation themselves: packaged production
containers reject missing `CORTEX_*_PUBLIC_URL` values as well as localhost,
documentation-placeholder, non-HTTPS, or nested-path public URLs before operators follow
bad cross-surface navigation inside the shipped UI. Those values are injected into a
runtime `cortex-runtime-config.js` file when the container starts, so the same packaged
browser image can be reused across client domains without a rebuild.
The fixed console also prefers the runtime `deployment-config` query URL from
`GET /health/startup` for its cross-surface employee-view link, so the operator surface
tracks the live package contract instead of relying only on its local runtime file.

The package images now force an explicit PyTorch wheel source before Docling installs its
OCR/layout dependencies. The shipped local profile defaults to the CPU wheel channel:

- `CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL=https://download.pytorch.org/whl/cpu`
- `CORTEX_PACKAGE_PYTORCH_PREINSTALL=torch torchvision`

For intentional NVIDIA deployments, operators must point
`CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL` at the matching CUDA wheel channel before
rebuilding `api`, `worker`, and `migrate`. This keeps CPU verification builds from
silently ballooning with CUDA-only artifacts while preserving explicit accelerator-driven
client packaging.

## Health checks

The package exposes:

- `GET /health/live`
- `GET /health/startup`
- `GET /health/ready`

`startup` validates static deployment configuration such as host/public URL alignment,
object-storage access, parser availability, accelerator expectations, and the local-model
network policy without waiting for PostgreSQL or Ollama round trips.

In packaged production profiles, the API now treats degraded static startup health as a
fail-closed condition during process startup. That keeps direct Kubernetes/ECS/OpenShift
rollouts aligned with the same contract that `package:up` enforces in the compose bundle.

The packaged worker exposes the same principle through
`python -m cortex.worker --check-startup`, which the shipped Compose, Kubernetes, and ECS
manifests use for worker health signaling.

`ready` adds live dependency checks for:

- PostgreSQL connectivity
- pgvector extension presence
- model endpoint reachability and pinned model availability
- object-storage access
- website-ingestion allowlist visibility

Both health endpoints return per-component `severity`, `detail`, and `remediation`
fields so operators and the fixed console show the same troubleshooting guidance.
Those components now include the declared packaged model and identity profiles as well,
the packaged Torch wheel/build profile, so operators can verify which generator,
embedding model, required accelerator, auth mode, issuer, audience, and container build
channel a deployment is advertising before they debug deeper runtime failures.
The fixed console now consumes both `startup` and `ready` directly, which keeps
fail-closed package boot checks distinct from live runtime dependency drift in the
operator UI.
If that identity profile is still `fixture` in a packaged production-style deployment,
the runtime health payload surfaces it as a warning rather than silently treating it as
production-ready authentication.

The packaged operator scripts now verify the split-host contract directly:

- `package:up` waits for `startup` and `ready` on both browser hosts
- `package:up` confirms that the console host emits `X-Cortex-Surface: console`
  and the query host emits `X-Cortex-Surface: query`
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, `package:up` now also proves both routed browser
  hosts publish the expected runtime `cortex-runtime-config.js` values and no-store cache
  policy before reporting success
- when `CORTEX_QUERY_SURFACE_MODE=external`, `package:up` instead proves the employee host
  is API-only by requiring `GET /` to return `404` while still carrying
  `X-Cortex-Surface: query`
- `package:up` now also waits for the live replacement-query request/response schema
  endpoints and fails if the contract descriptor stops advertising their stable paths,
  so client-owned employee UIs never inherit a half-published wire contract
- package helper scripts now fail early with a clear operator message when Docker is
  installed but the daemon/runtime is not reachable
- `package:up` blocks early on placeholder domains, non-HTTPS public URLs, relative object-storage roots, and unintended public model endpoints
- `package:up` prints `docker compose ps` plus recent `api`/`worker`/`edge` logs when the package still fails to reach a healthy state
- `package:up` also waits for the worker startup-check contract to pass before declaring the package ready
- `package:status` prints both routed health views plus the observed surface identity
- `package:status` now also prints the startup-health deployment contract summary for
  the live console/query public URLs, fail-closed startup policy, and declared
  `querySurfaceMode`
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, `package:status` prints the runtime
  `cortex-runtime-config.js` public URLs served by both browser hosts plus the observed
  no-store cache policy
- when `CORTEX_QUERY_SURFACE_MODE=external`, `package:status` reports the query host as
  `external-query-ui (not bundled)` and prints the employee-host root status so operators
  can confirm it stays API-only
- `package:status` prints the worker startup-check result from the running package
- the fixed console also reads the shared `GET /health/worker-startup` contract so operators
  can inspect durable-job safety without leaving the product, while `package:verify` still
  proves that same gate inside the real worker container
- `package:status` now also prints the routed worker-startup contract payload itself so
  host-routed API checks, fixed-console views, and worker-container probes stay aligned
- `package:status` also prints the live external query-contract summary exported by the query host
- `package:status` now also prints compact summaries of the live request/response schema endpoints exported for replacement query UIs
- `package:status` now also emits a single `replacement query contract readiness` summary
  so operators can see immediately whether the descriptor plus both wire schemas are all
  live, instead of having to mentally combine three separate sections
- that contract summary now also includes `querySurfaceMode` and `bundledQueryUiAvailable`
  so operators can confirm whether the running package ships `query-web` or expects a
  client-owned employee shell
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, `package:verify` confirms both browser hosts
  expose the expected runtime `cortex-runtime-config.js` values for console/query public
  URLs and that both serve the file with a `no-store` cache policy
- `package:verify` confirms the query host publishes `GET /v1/chat/contracts/v1` for replacement UI discovery
- `package:verify` also confirms the query host publishes the live request/response schema endpoints for replacement UI validation
- `package:verify` now also confirms the startup-health `deployment-config` detail still
  matches the shipped console/query public URLs, `startupPolicy=fail-closed`, and
  declared `querySurfaceMode`
- `package:verify` now also confirms the live contract advertises the expected
  `querySurfaceMode` and `bundledQueryUiAvailable` values for the chosen package mode
- `package:verify` confirms that live contract still advertises the expected request semantics,
  employee-safe versus operator-only field boundary, and stable machine-readable error meanings
- `package:verify` confirms the worker startup-check contract passes inside the running package
- `package:verify` confirms the replacement-query facade emits stable Cortex contract headers for trace, evidence status, route, and abstention
- the edge proxy grants `/v1/` requests a 300-second upstream read/send window so offline local-model calls can complete behind Nginx without surfacing a false `504`

In `external` query-surface mode, those operator scripts keep the API/contract checks on
the query host, intentionally skip bundled `query-web` HTML/runtime-config assertions,
and prove the employee host is still the routed Cortex query surface by checking both
`GET / -> 404` and `X-Cortex-Surface: query`. The package reports that mode explicitly so
operators can tell “client-owned employee shell” from “broken bundled employee shell”
without inspecting compose files by hand.

## Development Defaults

Local development keeps two independent frontend dev servers:

- console: `http://127.0.0.1:5173`
- app: `http://127.0.0.1:5174`

The example package compose file uses:

- `cortex-console.hrudainirmal.in`
- `cortex-app.hrudainirmal.in`

Those are examples only and must be replaced for client environments.
