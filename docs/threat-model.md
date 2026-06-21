# Threat Model

## Protected Assets
- Authorized document content, source metadata, query/response traces, typed memory, credentials, pipeline definitions, and audit evidence.

## Principal Threats and Controls
- Cross-scope retrieval: mandatory SQL predicates, ACL indexes, cache scope fingerprints, final result assertion, and adversarial tests.
- Prompt injection in documents: treat retrieved text as untrusted data, prohibit dynamic tools, validate claim support, and preserve suspicious spans for review.
- Stale authorization cache: include enterprise, principal-set hash, document version, pipeline version, and freshness epoch in cache keys.
- Duplicate or partial ingestion: deterministic identifiers, idempotent upserts, inactive processing versions, and transactional activation.
- Sensitive retention: separate trace payloads from content-free audit events; expire and purge them independently.
- Arbitrary computation: allowlisted pure functions only; no generated Python, shell, write SQL, or dynamic code.
- Model supply chain: offline artifacts, pinned digests, license manifest, and promotion evaluation.
- OCR performance regression: explicit accelerator requirement and fail-closed MPS development profile.

## Trust Assumptions
- PostgreSQL administrators and deployment operators are privileged.
- TLS termination and encrypted volumes are deployment responsibilities documented in production manifests.
