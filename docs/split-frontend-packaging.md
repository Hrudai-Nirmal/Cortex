# Split Frontend Packaging

## Purpose

Cortex ships its developer console and built-in query UI as separate frontend images.
This keeps the operator surface isolated from the employee-facing app and matches
enterprise deployment patterns where clients use distinct domains such as:

- `cortex-console.company.com`
- `cortex-app.company.com`

The query UI remains replaceable. Clients may keep the shipped `query-web` image or
replace it with their own chat shell while continuing to call the Cortex API.

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

For Kubernetes environments such as EKS, AKS, GKE, OpenShift, and RKE2, the same host
split is expressed through ingress rules in `infra/k8s/cortex-package.yaml`.

Adjacent platform examples now ship as well:

- `infra/openshift/cortex-package-routes.yaml` maps `/v1` and `/health` to `cortex-api` and `/` to the correct frontend service per host
- `infra/ecs/cortex-task-family.json` shows an ECS task-family baseline with split-host environment variables and shared object storage
- `infra/ecs/cortex-migrate-task.json` keeps ECS schema rollout as a separate one-shot task

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
- `VITE_CORTEX_CONSOLE_PUBLIC_URL`
- `VITE_CORTEX_QUERY_PUBLIC_URL`

Model-profile values are also deployment-critical in the packaged flow:

- `CORTEX_ENVIRONMENT=production`
- `CORTEX_DEV_MODE=false`
- `CORTEX_GENERATOR_MODEL`
- `CORTEX_EMBEDDING_MODEL`
- `CORTEX_REQUIRED_ACCELERATOR`

Do not hardcode the development domains in client builds.

## Health checks

The package exposes:

- `GET /health/live`
- `GET /health/startup`
- `GET /health/ready`

`startup` validates static deployment configuration such as host/public URL alignment,
object-storage access, parser availability, accelerator expectations, and the local-model
network policy without waiting for PostgreSQL or Ollama round trips.

`ready` adds live dependency checks for:

- PostgreSQL connectivity
- pgvector extension presence
- model endpoint reachability and pinned model availability
- object-storage access
- website-ingestion allowlist visibility

Both health endpoints return per-component `severity`, `detail`, and `remediation`
fields so operators and the fixed console show the same troubleshooting guidance.
Those components now include the declared packaged model and identity profiles as well,
so operators can verify which generator, embedding model, required accelerator, auth
mode, issuer, and audience a deployment is advertising before they debug deeper runtime
failures.
If that identity profile is still `fixture` in a packaged production-style deployment,
the runtime health payload surfaces it as a warning rather than silently treating it as
production-ready authentication.

The packaged operator scripts now verify the split-host contract directly:

- `package:up` waits for `startup` and `ready` on both browser hosts
- `package:up` confirms that the console host emits `X-Cortex-Surface: console`
  and the query host emits `X-Cortex-Surface: query`
- `package:status` prints both routed health views plus the observed surface identity

## Development Defaults

Local development keeps two independent frontend dev servers:

- console: `http://127.0.0.1:5173`
- app: `http://127.0.0.1:5174`

The example package compose file uses:

- `cortex-console.hrudainirmal.in`
- `cortex-app.hrudainirmal.in`

Those are examples only and must be replaced for client environments.
