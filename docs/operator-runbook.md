# Operator Runbook

## Purpose

This runbook is for operators deploying the shippable Cortex package on client-managed
infrastructure. It covers the split-host package bundle, the required domain variables,
and the minimum validation flow before user traffic is allowed.

## Package surfaces

Cortex ships these deployable images:

- `api`
- `worker`
- `console-web`
- `query-web`
- `edge`

The `console-web` image is the fixed first-party operator surface.
The `query-web` image is optional and may be replaced by a client-owned chat UI that
calls the external query contract.

## Required host split

Operators must provide two distinct browser hosts:

- `CORTEX_CONSOLE_HOST`
- `CORTEX_QUERY_HOST`

And matching public URLs:

- `CORTEX_CONSOLE_PUBLIC_URL`
- `CORTEX_QUERY_PUBLIC_URL`

The public URL hostnames must match the corresponding host values exactly.

## Docker package workflow

1. Copy `.env.package.example` to `.env.package`
2. Replace the example domains with the real client domains
3. Review model endpoint, database, and object-storage values
4. Start the package:

```bash
pnpm package:up
```

The first image build can take a while because the offline parsing stack bundles Docling
and its local model/runtime dependencies into the API and worker images.

5. Verify the running package:

```bash
pnpm package:verify
```

6. Inspect status or logs when needed:

```bash
pnpm package:status
pnpm package:logs
pnpm package:logs .env.package api
```

7. Stop it when needed:

```bash
pnpm package:down
```

To remove package volumes as well:

```bash
./scripts/package-down.sh .env.package --volumes
```

If `package:up` reports degraded readiness because Ollama is reachable but the configured
models are missing, pull them into the running package:

```bash
pnpm package:pull-models
pnpm package:verify
```

## What `package:up` validates

Before starting containers, the script validates:

- env file presence
- required domain variables
- distinct console/query hosts
- public URL host alignment
- Docker Compose rendering

After startup, it waits for:

- `GET /health/startup`
- `GET /health/ready`
- query-surface HTML through the split host router

The package also runs database migrations before `api` and `worker` proceed.

## What `package:verify` checks

- console host routes to the operator frontend
- query host routes to the employee frontend
- both frontend hosts emit explicit `X-Cortex-Surface` headers
- `live`, `startup`, and `ready` health endpoints respond
- if fixture auth is enabled:
  - seed fixtures load
  - `POST /v1/chat/completions` returns the OpenAI-compatible Cortex contract, contract-version headers, and Cortex evidence metadata
  - contract identity includes `traceEventsPath` for persisted SSE progress handoff

## What `package:status` and `package:logs` do

- `package:status` prints the current `startup` and `ready` component states for the console host,
  including severity and remediation guidance for every non-ready component
- `package:logs` tails compose logs for the whole package or one named service

## Health endpoints

- `GET /health/live`: process liveness only
- `GET /health/startup`: static deployment validation
- `GET /health/ready`: live dependency readiness

`startup` is the first place operators should look when a package fails because of bad
host/domain configuration, invalid public URLs, storage issues, parser availability, or
offline-policy violations.

`package:up` now surfaces any degraded startup/readiness components immediately, including
their severity and remediation guidance, instead of only reporting a timeout.

`ready` adds live checks for:

- PostgreSQL connectivity
- pgvector extension availability
- Ollama/model availability
- object storage
- accelerator expectations
- website-ingestion configuration visibility

Each runtime component now includes:

- `status`: `ready`, `degraded`, or `unavailable`
- `severity`: whether the signal is informational or an operator-blocking error
- `detail`: the observed runtime state
- `remediation`: the next concrete operator action

An empty website allowlist no longer blocks package readiness. Cortex reports it as an
uploads-only deployment and tells operators how to enable allowlisted website ingestion.

## Replaceable query UI guidance

When clients use their own chat UI:

- keep `console-web`
- keep `api`
- call `POST /v1/chat/completions`
- render citations from `x_cortex.citations`
- preserve `x_cortex.traceId` for feedback and support workflows

The custom query UI must not send raw access-scope principals from the browser. Cortex
derives scope from the authenticated user token.

## Kubernetes, OpenShift, and ECS notes

### Kubernetes, EKS, AKS, GKE, RKE2

- use host-based ingress rules for console and query hosts
- keep separate services for `console-web`, `query-web`, and `api`
- use the provided startup/readiness/liveness probes as the baseline
- run the migration job before promoting the API and worker deployments
- replace the example `.example.com` hosts in `infra/k8s/cortex-package.yaml` with the client-owned console and app domains before deployment
- populate `cortex-secrets` with database and model endpoint values while keeping shared non-secret package settings in `cortex-config`
- mount persistent storage for `/var/lib/cortex/object-storage` so uploads, website snapshots, and parsed source blobs survive pod restarts

### OpenShift

- map the same split hosts through Routes or an ingress controller
- preserve the same host-based routing behavior
- `infra/openshift/cortex-package-routes.yaml` provides a ready-to-edit Route example
  that sends both client-owned hosts to the packaged `edge` service
- ensure any SecurityContext constraints still allow the object-storage mount path and
  nginx/http serving model you choose
- treat schema migration as a Job or pre-deploy hook rather than an ad hoc shell step

### ECS

- map console/query hosts through ALB host-based listener rules
- run `api`, `worker`, `console-web`, and `query-web` as separate services or tasks
- keep `edge` only if you want the Nginx host router inside the package rather than at the ALB layer
- run the migration command as a one-shot task before the API service rolls forward
- back the object-storage root with durable shared storage or a compatible mounted filesystem volume for `api` and `worker`
- `infra/ecs/cortex-task-family.json` shows an edit-in-place task-family baseline with
  separate packaged services, EFS-backed object storage, and the split-host environment contract

## Failure hints

- `consolePublicUrl host must match consoleHost`:
  operator domains do not align
- `database ready but pgvector extension is missing`:
  PostgreSQL is up, but the vector extension is not installed
- `missing models:`:
  Ollama is reachable but the configured model names are not present
- `model endpoint host ... is not local or private`:
  Cortex detected a public model endpoint while remote model usage is not explicitly allowed
- `worker startup blocked by runtime health checks`:
  the worker refused to enter its durable job loop because one or more startup or live
  readiness checks failed; inspect `pnpm package:status` and `pnpm package:logs .env.package worker`
