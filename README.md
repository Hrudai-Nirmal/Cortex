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

See [context.md](context.md), [architecture.md](docs/architecture.md),
[split-frontend-packaging.md](docs/split-frontend-packaging.md), and
[threat-model.md](docs/threat-model.md).
