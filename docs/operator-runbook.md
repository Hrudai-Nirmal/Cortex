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

Inside the fixed console, operators can now distinguish:

- the currently active immutable pipeline version
- validated versions waiting activation
- retired versions that remain eligible for explicit rollback
- a lifecycle queue that turns those release states into explicit promotion and rollback actions

The console trace timeline now also shows:

- validated answer preview
- persisted claim support status
- claim-to-citation linkage beside stage evidence
- ranked retrieved evidence rows with source, locator, and scoring detail

The console settings view now foregrounds:

- packaged model profile
- packaged build profile
- packaged identity profile
- packaged query-surface mode (`bundled` or `external`)
- live replacement-query contract metadata from the running API
- one surface-deployment contract table that makes split-host isolation, startup policy,
  and replacement-query contract availability explicit in a single operator view
- distinct startup-contract and live-readiness sections so operators can see whether
  Cortex should fail closed during packaged boot or whether a dependency degraded after boot

## Required host split

Operators must provide two distinct browser hosts:

- `CORTEX_CONSOLE_HOST`
- `CORTEX_QUERY_HOST`

And matching public URLs:

- `CORTEX_CONSOLE_PUBLIC_URL`
- `CORTEX_QUERY_PUBLIC_URL`

The public URL hostnames must match the corresponding host values exactly.
They must also stay rooted at the host with no extra path, query string, or fragment,
and packaged production surfaces must use `https://`.
The shipped browser images now fail closed on this too: if the packaged
`CORTEX_CONSOLE_PUBLIC_URL` or `CORTEX_QUERY_PUBLIC_URL` values are missing or still
point at localhost, documentation placeholders, or nested paths, the fixed console/query
surfaces will reject the configuration instead of quietly rendering bad cross-surface
links. Those values are injected at container startup, so client deployments do not need
to rebuild the browser images just to change domains.
When the fixed console can reach `GET /health/startup`, it also prefers the runtime
`deployment-config` query URL for the “Open employee view” link. That keeps the
operator-facing console aligned with the live package contract even if a browser image
starts with stale local runtime state and the API package advertises newer deployment
URLs through startup health.

## Docker package workflow

1. Copy `.env.package.example` to `.env.package`
2. Replace the example domains with the real client domains
3. Choose the employee surface packaging mode:
   - keep `CORTEX_QUERY_SURFACE_MODE=bundled` when Cortex ships the built-in `query-web`
   - switch to `CORTEX_QUERY_SURFACE_MODE=external` when the client keeps its own employee chat shell and Cortex should ship only the fixed console plus API/worker package
4. Review model endpoint, database, and object-storage values
5. Keep the public URLs rooted at the host itself, for example `https://cortex-app.company.com`
   instead of `https://cortex-app.company.com/chat`
6. Start the package:

```bash
pnpm package:up
```

The first image build can take a while because the offline parsing stack bundles Docling
and its local model/runtime dependencies into the API and worker images.
The package also preinstalls PyTorch from `CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL`
before Docling resolves its model/runtime stack so the default CPU verification profile
does not silently pull CUDA-heavy Linux artifacts.
If Docker is installed but the daemon is not reachable, the package scripts now fail fast
with an operator-facing message that tells you to start Docker Desktop or the target
container runtime before continuing.

7. Verify the running package:

```bash
pnpm package:verify
```

8. Inspect status or logs when needed:

```bash
pnpm package:status
pnpm package:logs
pnpm package:logs .env.package api
```

9. Stop it when needed:

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

`package:pull-models` only applies to the bundled local Ollama service. If the client
deployment intentionally sets `CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=true`, pull the required
models or provision the equivalent artifacts directly on that remote provider instead of
using the local package helper.

If a client deployment intentionally targets NVIDIA Linux workers, set
`CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL` to the matching PyTorch CUDA wheel channel and
rebuild the package images before rollout. Keep the default CPU wheel channel for
Docker Desktop, ECS CPU tasks, and other non-CUDA verification environments.

## What `package:up` validates

Before starting containers, the script validates:

- env file presence
- production package profile (`CORTEX_ENVIRONMENT=production`, `CORTEX_DEV_MODE=false`)
- query surface packaging mode (`CORTEX_QUERY_SURFACE_MODE=bundled|external`)
- required domain variables
- placeholder-domain replacement (`example.com`-style hosts are rejected until edited)
- required model-profile variables
- distinct console/query hosts
- public URL host alignment
- HTTPS root-only public URLs for both browser surfaces
- absolute object-storage root path
- explicit non-`auto` accelerator declaration (`cpu`, `mps`, or `cuda`)
- local/private model-endpoint policy unless remote model access is explicitly allowed
- Docker Compose rendering

The Kubernetes and ECS examples now pin `CORTEX_QUERY_SURFACE_MODE` explicitly as well.
Treat that as part of the deployment contract, not an optional override, because it
controls whether the employee host is a bundled `query-web` surface or a client-owned
API-only integration boundary.

When a packaged runtime still starts with invalid environment values, the API/worker now
collapse Pydantic settings validation into a single operator-facing
`invalid Cortex settings: ...` error string. That keeps bad public URLs, host mismatches,
or relative storage paths from disappearing into a generic Python traceback.

Inside the fixed developer console, the Settings tab now also exposes an
`Operator release gate` checklist. It summarizes whether the package is safe to ship by
combining:

- startup-safe deployment validation
- live runtime dependency readiness
- active immutable pipeline presence
- validated-but-not-yet-promoted pipeline versions
- live external query-contract availability
- the outcome of the latest persisted evidence-bearing trace

After startup, it waits for:

- `GET /health/startup` through both console and query hosts
- `GET /health/ready` through both console and query hosts
- console and query HTML through the split host router
- `X-Cortex-Surface` identity headers on both routed browser hosts
- `cortex-runtime-config.js` through both routed browser hosts, including the expected
  console/query public URLs and `Cache-Control: no-store, no-cache, must-revalidate`
- `python -m cortex.worker --check-startup` inside the worker container

When `CORTEX_QUERY_SURFACE_MODE=external`, the same package flow switches to the
dedicated `docker-compose.package.external-query.yml` bundle. In that mode Cortex still
verifies the query-host `startup`, `ready`, and `GET /v1/chat/contracts/v1` API
boundary, but it intentionally skips bundled `query-web` HTML/runtime-config checks
because the employee browser shell is client-owned and shipped outside the package.

The package also runs database migrations before `api` and `worker` proceed.
The packaged worker now publishes its own exec-style startup contract through
`python -m cortex.worker --check-startup`, and the shipped Compose/Kubernetes/ECS
examples wire that into their worker health signals.

## What `package:verify` checks

- console host routes to the operator frontend
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, query host routes to the employee frontend
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, both frontend hosts emit explicit `X-Cortex-Surface` headers
- `live`, `startup`, and `ready` health endpoints respond through both browser hosts
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, both browser hosts publish `cortex-runtime-config.js` with the expected console/query public URLs
- when `CORTEX_QUERY_SURFACE_MODE=bundled`, both browser hosts serve `cortex-runtime-config.js` with a no-store cache policy so split-host domain changes are not hidden behind stale browser state
- the query host publishes `GET /v1/chat/contracts/v1` for replacement UI discovery
- that contract descriptor now also publishes `querySurfaceMode` plus
  `bundledQueryUiAvailable`, so operators can verify whether the package ships the
  employee shell or expects a client-owned one
- that contract descriptor still declares the expected request semantics for replacement UIs:
  `userMessageSelectionPolicy=last-non-empty-user-message`, `streamRequiredValue=false`,
  and `supportsCitationToggle=true`
- that contract descriptor still separates employee-safe `x_cortex` fields from
  operator-only trace correlation fields
- that contract descriptor still publishes stable machine-readable error meanings for
  `invalid_request`, `forbidden_scope`, `provider_unavailable`, and `internal_error`
- the worker startup check passes from inside the running package
- if fixture auth is enabled:
  - seed fixtures load
  - `POST /v1/chat/completions` returns the OpenAI-compatible Cortex contract, contract-version headers, and Cortex evidence metadata
  - response headers include evidence status, route, and abstention signals for thin clients and gateway logging
  - contract identity includes `traceEventsPath` for persisted builder/operator trace replay
  - the edge proxy allows up to 300 seconds for `/v1/` responses so cold local-model calls do not fail with a spurious `504 Gateway Timeout`

## What `package:status` and `package:logs` do

- `package:status` prints the current `startup` and `ready` component states for the console host,
  query host, routed surface identity, browser runtime-config URLs, worker startup-check result, and the live external query-contract summary, including request semantics, employee-safe versus operator-only fields, stable error meanings, severity, and remediation guidance for every non-ready component
- when `CORTEX_QUERY_SURFACE_MODE=external`, `package:status` makes that explicit and
  reports the query host as `external-query-ui (not bundled)` instead of pretending a
  packaged `query-web` shell exists
- when the live query-contract endpoint itself is unavailable, `package:status` now keeps the rest
  of the package summary readable and prints that contract fetch failure as a degraded detail
- `package:verify` now fails with explicit labels such as the missing routed surface, runtime-config
  drift, blocked worker startup check, or query-contract field that broke, and points operators back
  to `pnpm package:status` for the fuller routed health summary
- `package:logs` tails compose logs for the whole package or one named service

The fixed console now mirrors that packaging story more directly: even if one settings-side
endpoint such as `GET /v1/chat/contracts/v1` is temporarily unavailable, the operator surface
still loads and surfaces the missing dependency as a degraded deployment-contract check instead
of failing closed on the entire browser UI.
The source operations lane now follows the same operator-first pattern: failed, quarantined,
processing, and stale-live-version onboarding states are grouped into an operator queue so
builders can start with the next repair action instead of scanning raw version metadata.

## Health endpoints

- `GET /health/live`: process liveness only
- `GET /health/startup`: static deployment validation
- `GET /health/ready`: live dependency readiness

`startup` is the first place operators should look when a package fails because of bad
host/domain configuration, invalid public URLs, storage issues, parser availability, or
offline-policy violations.

`package:up` now surfaces any degraded startup/readiness components immediately, including
their severity and remediation guidance, instead of only reporting a timeout.

It also blocks immediately on the most common packaging mistakes:

- unchanged documentation placeholder domains
- HTTP or nested-path public browser URLs
- relative object-storage mount paths
- public remote model endpoints when `CORTEX_ALLOW_REMOTE_MODEL_ENDPOINT=false`

If the package still fails to become healthy after container boot, `package:up` now
prints:

- `docker compose ps` output for the packaged services
- recent `api`, `worker`, and `edge` logs

That makes it much easier to distinguish an API fail-closed startup exit from an edge
routing issue or a worker-only readiness problem.

`ready` adds live checks for:

- PostgreSQL connectivity
- pgvector extension availability
- Ollama/model availability
- object storage
- object-storage probe file creation and deletion
- accelerator expectations
- website-ingestion configuration visibility

Each runtime component now includes:

- `status`: `ready`, `degraded`, or `unavailable`
- `severity`: whether the signal is informational or an operator-blocking error
- `detail`: the observed runtime state
- `remediation`: the next concrete operator action

The readiness payload now includes:

- `model-profile` for the declared generator model, embedding model, and required accelerator
- `package-build-profile` for the packaged Torch wheel channel and preinstalled model-runtime packages
- `identity-profile` for the declared auth mode plus OIDC issuer and audience contract
- `deployment-config` with the split-host browser origins plus `startupPolicy=fail-closed|report-only`

When the packaged deployment is still running with `authMode=fixture`, Cortex reports
that identity profile as a warning so operators do not mistake evaluation auth for the
final client rollout boundary.

For packaged production profiles (`CORTEX_ENVIRONMENT=production`, `CORTEX_DEV_MODE=false`),
the API now fails closed during lifespan startup if static startup health is degraded.
That behavior is intentional: Kubernetes, OpenShift, and ECS operators should see a
crash-looping or non-ready API rather than a partially valid deployment that only fails
later under real onboarding or query traffic.

An empty website allowlist no longer blocks package readiness. Cortex reports it as an
uploads-only deployment and tells operators how to enable allowlisted website ingestion.

## Replaceable query UI guidance

When clients use their own chat UI:

- keep `console-web`
- keep `api`
- read `GET /v1/chat/contracts/v1` at startup to confirm the live Cortex package still exports the expected `v1` contract, request semantics, and employee-safe field boundary
- call `POST /v1/chat/completions`
- render citations from `x_cortex.citations`
- preserve `x_cortex.traceId` for feedback and support workflows
- preserve `X-Cortex-Route` and `X-Cortex-Abstained` if your gateway, BFF, or observability layer logs response headers for support workflows
- treat `employeeSafeExtensionFields` as the supported browser dependency boundary for the employee shell
- treat `x_cortex.traceEventsPath` as operator-only trace correlation unless the client intentionally runs an elevated builder/debug integration

The bundled `query-web` surface now follows this same pattern itself: it loads the live
contract descriptor at startup, verifies the response headers it depends on, and fails
closed with an employee-safe error if the deployed package no longer matches the expected
public query contract.

The custom query UI must not send raw access-scope principals from the browser. Cortex
derives scope from the authenticated user token.

When operators promote or roll back pipeline versions in the console, Cortex activates
only immutable versions and keeps audit evidence for both forward promotion and rollback.

## Kubernetes, OpenShift, and ECS notes

### Kubernetes, EKS, AKS, GKE, RKE2

- use host-based ingress rules for console and query hosts
- keep separate services for `console-web`, `query-web`, and `api`
- use the provided startup/readiness/liveness probes as the baseline
- keep the worker exec probes that run `python -m cortex.worker --check-startup`; they are the packaged signal that database/model/object-storage readiness is safe for durable jobs
- run the migration job before promoting the API and worker deployments
- replace the example `.example.com` hosts in `infra/k8s/cortex-package.yaml` with the client-owned console and app domains before deployment
- use `infra/k8s/cortex-package-external-query.yaml` instead when the client keeps its own employee chat shell and only Cortex console/API/worker ship inside the package
- keep the ConfigMap public URLs rooted at the host and HTTPS once the real client domains are substituted
- populate `cortex-secrets` with database and model endpoint values while keeping shared non-secret package settings in `cortex-config`
- mount persistent storage for `/var/lib/cortex/object-storage` so uploads, website snapshots, and parsed source blobs survive pod restarts

### OpenShift

- map the same split hosts through Routes or an ingress controller
- preserve the same host-based routing behavior
- `infra/openshift/cortex-package-routes.yaml` provides a ready-to-edit Route example
  that maps `/v1` and `/health` to `cortex-api` while routing `/` to the correct
  console or query frontend service for each host
- `infra/openshift/cortex-package-external-query-routes.yaml` provides the matching
  API-only Route example for client-owned employee chat shells
- ensure any SecurityContext constraints still allow the object-storage mount path and
  nginx/http serving model you choose
- treat schema migration as a Job or pre-deploy hook rather than an ad hoc shell step

### ECS

- map console/query hosts through ALB host-based listener rules
- run `api`, `worker`, `console-web`, and `query-web` as separate services or tasks
- keep `edge` only if you want the Nginx host router inside the package rather than at the ALB layer
- preserve the worker container health check that runs `python -m cortex.worker --check-startup`
- run the migration command as a one-shot task before the API service rolls forward
- back the object-storage root with durable shared storage or a compatible mounted filesystem volume for `api` and `worker`
- `infra/ecs/cortex-task-family.json` shows an edit-in-place task-family baseline with
  separate packaged services, EFS-backed object storage, and the split-host environment contract
- `infra/ecs/cortex-migrate-task.json` provides the matching one-shot migration task so
  schema rollout stays explicit instead of being hidden inside service startup
- `infra/ecs/cortex-task-family-external-query.json` provides the API-only Cortex package mode
  for clients who keep the fixed console and Cortex APIs but supply their own employee chat UI

## Failure hints

- `consolePublicUrl host must match consoleHost`:
  operator domains do not align
- `production public URLs must use https`:
  one or both browser-surface URLs are still configured for plaintext HTTP
- `public URL must not include a path, query string, or fragment`:
  the packaged split-host UI was pointed at a nested route instead of the host root
- `database ready but pgvector extension is missing`:
  PostgreSQL is up, but the vector extension is not installed
- `missing models:`:
  Ollama is reachable but the configured model names are not present
- `model endpoint host ... is not local or private`:
  Cortex detected a public model endpoint while remote model usage is not explicitly allowed
- `production consoleHost/queryHost must be real client domains, not documentation placeholders`:
  `package:up` or the runtime settings still contain the example hostnames from the docs
- `worker startup blocked by runtime health checks`:
  the worker refused to enter its durable job loop because one or more startup or live
  readiness checks failed; inspect `pnpm package:status` and `pnpm package:logs .env.package worker`
