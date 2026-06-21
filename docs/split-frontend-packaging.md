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

## Domain Configuration

Domain values are deployment-critical and must be supplied by the operator:

- `CORTEX_CONSOLE_HOST`
- `CORTEX_QUERY_HOST`
- `VITE_CORTEX_CONSOLE_PUBLIC_URL`
- `VITE_CORTEX_QUERY_PUBLIC_URL`

Do not hardcode the development domains in client builds.

## Development Defaults

Local development keeps two independent frontend dev servers:

- console: `http://127.0.0.1:5173`
- app: `http://127.0.0.1:5174`

The example package compose file uses:

- `cortex-console.hrudainirmal.in`
- `cortex-app.hrudainirmal.in`

Those are examples only and must be replaced for client environments.
