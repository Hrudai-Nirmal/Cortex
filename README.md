# Cortex

Cortex is an offline-capable, evidence-bounded RAG pipeline builder for dedicated enterprise deployments. It separates a graph-first developer console from a focused employee query experience while sharing the same authorization, provenance, citation, and audit controls.

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

The web console runs at `http://127.0.0.1:5173`; the API runs at `http://127.0.0.1:8000`.

`pnpm dev:up` starts PostgreSQL and Ollama through Docker Compose, applies migrations, and launches the API, worker, and web surfaces as local background processes. `pnpm dev:seed` loads the deterministic integration fixture set.

## Source onboarding

- Developer source operations live under `/developer` in the `Sources` and `Jobs` tabs.
- Supported source formats: PDF, DOCX, HTML, TXT/Markdown, and CSV.
- Uploads are stored once by raw SHA-256 beneath `CORTEX_OBJECT_STORAGE_ROOT`, then ingested through durable jobs.
- Single-page website ingestion is restricted to `CORTEX_WEBSITE_ALLOWLIST`.
- macOS development profiles still fail closed if Docling OCR falls back from MPS to CPU.

## Profiles

- `development-macos`: requires MPS for accelerated Docling model stages and fails closed on an unexpected CPU fallback.
- `development-cpu`: explicit CPU profile for CI or machines without Metal.
- `production`: requires the operator to select the expected accelerator and model artifacts.

See [context.md](context.md), [architecture.md](docs/architecture.md), and [threat-model.md](docs/threat-model.md).
