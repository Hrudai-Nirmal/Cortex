# ADR 0001: Browser-First UI with an Electron-Ready Boundary

## Status
Accepted

## Decision
Implement the developer console and end-user query surface as one browser-first React application. Keep filesystem, update, and native integrations behind explicit adapters so a later Electron shell can reuse the compiled application.

## Rationale
Browser delivery best supports OIDC, Kubernetes, remote operations, embedded client chat, and offline private-network deployments. Electron adds packaging, signing, update, and desktop security work without improving the first RAG quality proof.
