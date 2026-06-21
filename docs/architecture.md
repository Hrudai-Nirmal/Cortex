# Cortex Architecture

```mermaid
flowchart LR
    UI["Developer Console / Query UI"] --> API["FastAPI Control Plane"]
    API --> AUTH["RBAC + ACL Scope"]
    AUTH --> CLASSIFY["Rules + Route Classifier"]
    CLASSIFY --> COMPUTE["Typed Compute Registry"]
    CLASSIFY --> RETRIEVE["Scoped Hybrid Retrieval"]
    RETRIEVE --> RRF["RRF + Top 40"]
    RRF --> RERANK["Cross-Encoder Reranker"]
    RERANK --> GENERATE["Bounded Claim Generation"]
    GENERATE --> VALIDATE["Claim/Span Validation"]
    VALIDATE --> UI
    WORKER["Ingestion Worker"] --> PARSE["Docling + OCR"]
    PARSE --> CHUNK["Deterministic Chunking"]
    CHUNK --> DB[("PostgreSQL + pgvector")]
    RETRIEVE --> DB
    API --> TRACE["Trace Memory"]
    API --> AUDIT["Content-Free Audit Log"]
```

## Deployment Boundary
The browser application is the canonical UI. A future Electron wrapper may load the same compiled assets and API contracts, but it must not become the only distribution path.

## Security Boundary
Every retrieval call requires an `AccessScope`. Enterprise and ACL principals are applied in both lexical and vector SQL before results leave PostgreSQL. A final authorization assertion guards returned rows as defense in depth.
