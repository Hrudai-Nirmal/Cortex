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

The built-in query UI remains optional and replaceable. The console is the default
operator surface and is not intended to be swapped out.

The bundled query UI now treats `sufficient`, `partial`, `insufficient`, and `conflict`
evidence states differently so client-owned chat shells have a trustworthy reference
consumer for the external contract.

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
- The console version lane now distinguishes active, validated, and retired immutable pipeline versions so operators can see promotable releases and explicit rollback targets.
- The console trace lane now shows validated answer preview, claim support status, citation linkage, and stage evidence together for faster operator review.
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
- runtime-health payloads that explicitly declare the packaged identity profile, including auth mode and OIDC contract
- container and ingress examples with readiness/liveness probes
- explicit host/public URL configuration for both browser surfaces
- explicit packaged model-profile declaration for generator, embeddings, and accelerator expectations
- explicit packaged production-profile declaration so client bundles do not inherit development-mode defaults
- an offline-capable model-endpoint policy check that flags unexpected remote model hosts
- package verification that checks split-surface identity headers, both routed health views, and query-contract identity headers
- package bootstrap/status now prove both routed browser hosts resolve to the expected Cortex surfaces before operators treat the package as healthy
- OpenShift Route and ECS task-family examples for client-owned split-host deployments, including a one-shot ECS migration task
- operator scripts:
  - `pnpm package:up`
  - `pnpm package:status`
  - `pnpm package:logs`
  - `pnpm package:pull-models`
  - `pnpm package:verify`
  - `pnpm package:down`

The worker now validates both startup-safe configuration and live dependency readiness
before it enters its durable job loop, so broken package deployments fail fast instead
of quietly polling forever.

`pnpm package:up` now prints the exact degraded startup/readiness components and their
remediation instead of failing with a generic timeout when package validation disagrees
with the deployment profile.

See [context.md](context.md), [architecture.md](docs/architecture.md),
[external-query-contract.md](docs/external-query-contract.md),
[operator-runbook.md](docs/operator-runbook.md),
[split-frontend-packaging.md](docs/split-frontend-packaging.md), and
[threat-model.md](docs/threat-model.md).
