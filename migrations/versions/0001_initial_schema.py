"""Create the initial Cortex persistence model and retrieval indexes."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create extension, tables, retention relationship, and scoped search indexes."""
    statements = (
        "CREATE EXTENSION IF NOT EXISTS vector",
        """
        CREATE TYPE document_version_status AS ENUM (
            'processing', 'active', 'superseded', 'failed', 'deleted'
        )
        """,
        """
        CREATE TYPE pipeline_status AS ENUM (
            'draft', 'validated', 'evaluated', 'approved', 'active', 'retired'
        )
        """,
        "CREATE TYPE memory_type AS ENUM ('policy', 'preference', 'factual', 'episodic', 'trace')",
        """
        CREATE TABLE enterprise (
            id UUID PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE document (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            source_uri TEXT NOT NULL,
            source_fingerprint BYTEA NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (enterprise_id, source_fingerprint)
        )
        """,
        """
        CREATE TABLE document_version (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            document_id UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
            version_hash BYTEA NOT NULL,
            version_label TEXT NOT NULL,
            raw_hash BYTEA NOT NULL,
            canonical_hash BYTEA NOT NULL,
            parser_version TEXT NOT NULL,
            source_authority DOUBLE PRECISION NOT NULL DEFAULT 0.85,
            published_at TIMESTAMPTZ,
            status document_version_status NOT NULL DEFAULT 'processing',
            extraction_diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_at TIMESTAMPTZ,
            UNIQUE (enterprise_id, document_id, version_hash)
        )
        """,
        """
        CREATE TABLE chunk (
            id BYTEA PRIMARY KEY CHECK (octet_length(id) = 32),
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            document_version_id UUID NOT NULL REFERENCES document_version(id) ON DELETE CASCADE,
            structural_locator TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            normalized_content TEXT NOT NULL,
            chunker_config_hash BYTEA NOT NULL CHECK (octet_length(chunker_config_hash) = 32),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            lexical TSVECTOR GENERATED ALWAYS AS (
                to_tsvector('english', normalized_content)
            ) STORED,
            embedding VECTOR(1024),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_version_id, ordinal)
        )
        """,
        """
        CREATE TABLE chunk_acl (
            chunk_id BYTEA NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            principal_id TEXT NOT NULL,
            PRIMARY KEY (chunk_id, principal_id)
        )
        """,
        """
        CREATE TABLE pipeline_version (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            status pipeline_status NOT NULL DEFAULT 'draft',
            definition JSONB NOT NULL,
            definition_hash BYTEA NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_at TIMESTAMPTZ,
            UNIQUE (enterprise_id, version),
            UNIQUE (enterprise_id, definition_hash)
        )
        """,
        """
        CREATE TABLE trace_memory (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            actor_id TEXT NOT NULL,
            raw_query TEXT NOT NULL,
            raw_response TEXT,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_content_expires_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE audit_log (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            trace_memory_id UUID REFERENCES trace_memory(id) ON DELETE SET NULL,
            trace_identifier_hash BYTEA NOT NULL CHECK (octet_length(trace_identifier_hash) = 32),
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            scope JSONB NOT NULL,
            pipeline_version INTEGER,
            model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
            outcome TEXT NOT NULL,
            event_payload JSONB NOT NULL,
            event_hash BYTEA NOT NULL CHECK (octet_length(event_hash) = 32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE typed_memory (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL,
            memory_type memory_type NOT NULL,
            status TEXT NOT NULL,
            content JSONB NOT NULL,
            provenance JSONB NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            expires_at TIMESTAMPTZ,
            review_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE durable_job (
            id UUID PRIMARY KEY,
            enterprise_id UUID NOT NULL REFERENCES enterprise(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            locked_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (enterprise_id, idempotency_key)
        )
        """,
        "CREATE INDEX chunk_enterprise_version_idx ON chunk (enterprise_id, document_version_id)",
        "CREATE INDEX chunk_lexical_idx ON chunk USING GIN (lexical)",
        "CREATE INDEX chunk_embedding_hnsw_idx ON chunk USING hnsw (embedding vector_cosine_ops)",
        "CREATE INDEX chunk_acl_scope_idx ON chunk_acl (enterprise_id, principal_id, chunk_id)",
        """
        CREATE INDEX document_version_active_idx ON document_version (enterprise_id, document_id)
        WHERE status = 'active'
        """,
        """
        CREATE UNIQUE INDEX document_one_active_version_idx ON document_version (document_id)
        WHERE status = 'active'
        """,
        "CREATE INDEX trace_memory_expiry_idx ON trace_memory (expires_at)",
        "CREATE INDEX audit_log_expiry_idx ON audit_log (expires_at)",
        "CREATE INDEX audit_log_trace_hash_idx ON audit_log (trace_identifier_hash)",
        """
        CREATE INDEX durable_job_claim_idx ON durable_job (status, available_at)
        WHERE status = 'queued'
        """,
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    """Remove the initial schema in reverse dependency order."""
    statements = (
        "DROP TABLE IF EXISTS durable_job",
        "DROP TABLE IF EXISTS typed_memory",
        "DROP TABLE IF EXISTS audit_log",
        "DROP TABLE IF EXISTS trace_memory",
        "DROP TABLE IF EXISTS pipeline_version",
        "DROP TABLE IF EXISTS chunk_acl",
        "DROP TABLE IF EXISTS chunk",
        "DROP TABLE IF EXISTS document_version",
        "DROP TABLE IF EXISTS document",
        "DROP TABLE IF EXISTS enterprise",
        "DROP TYPE IF EXISTS memory_type",
        "DROP TYPE IF EXISTS pipeline_status",
        "DROP TYPE IF EXISTS document_version_status",
    )
    for statement in statements:
        op.execute(statement)
