"""Extend the schema for source onboarding, persisted diagnostics, and blob deduplication."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add source onboarding tables, metadata columns, and deterministic version constraints."""
    statements = (
        """
        CREATE TABLE source_blob (
            raw_hash BYTEA PRIMARY KEY CHECK (octet_length(raw_hash) = 32),
            object_key TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "ALTER TABLE document ADD COLUMN display_name TEXT",
        "ALTER TABLE document ADD COLUMN source_type TEXT",
        "ALTER TABLE document ADD COLUMN created_by TEXT",
        "ALTER TABLE document ADD COLUMN updated_at TIMESTAMPTZ",
        """
        UPDATE document
        SET display_name = title,
            source_type = 'text',
            created_by = 'system',
            updated_at = created_at
        """,
        "ALTER TABLE document ALTER COLUMN display_name SET NOT NULL",
        "ALTER TABLE document ALTER COLUMN source_type SET NOT NULL",
        "ALTER TABLE document ALTER COLUMN created_by SET NOT NULL",
        "ALTER TABLE document ALTER COLUMN updated_at SET NOT NULL",
        "ALTER TABLE document_version ADD COLUMN acl_principals JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE document_version ADD COLUMN mime_type TEXT",
        "ALTER TABLE document_version ADD COLUMN object_key TEXT",
        "ALTER TABLE document_version ADD COLUMN parser_name TEXT",
        "ALTER TABLE document_version ADD COLUMN ingestion_status TEXT NOT NULL DEFAULT 'processing'",
        "ALTER TABLE document_version ADD COLUMN quarantine_status TEXT NOT NULL DEFAULT 'clear'",
        "ALTER TABLE document_version ADD COLUMN malware_status TEXT NOT NULL DEFAULT 'not-scanned'",
        "ALTER TABLE document_version ADD COLUMN failure_code TEXT",
        "ALTER TABLE document_version ADD COLUMN failure_detail TEXT",
        """
        ALTER TABLE document_version
        ADD COLUMN accelerator_reports JSONB NOT NULL DEFAULT '[]'::jsonb
        """,
        """
        UPDATE document_version
        SET parser_name = 'text-api',
            mime_type = 'text/plain',
            ingestion_status = CASE
                WHEN status = 'active' THEN 'active'
                WHEN status = 'failed' THEN 'failed'
                ELSE 'processing'
            END
        """,
        "ALTER TABLE document_version ALTER COLUMN parser_name SET NOT NULL",
        """
        CREATE UNIQUE INDEX document_version_raw_identity_idx
        ON document_version (enterprise_id, document_id, raw_hash, version_label)
        """,
        """
        CREATE INDEX document_version_source_status_idx
        ON document_version (enterprise_id, document_id, created_at DESC, ingestion_status)
        """,
        "CREATE INDEX document_updated_at_idx ON document (enterprise_id, updated_at DESC)",
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    """Remove source onboarding extensions while leaving the initial schema intact."""
    statements = (
        "DROP INDEX IF EXISTS document_updated_at_idx",
        "DROP INDEX IF EXISTS document_version_source_status_idx",
        "DROP INDEX IF EXISTS document_version_raw_identity_idx",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS accelerator_reports",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS failure_detail",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS failure_code",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS malware_status",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS quarantine_status",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS ingestion_status",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS parser_name",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS object_key",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS mime_type",
        "ALTER TABLE document_version DROP COLUMN IF EXISTS acl_principals",
        "ALTER TABLE document DROP COLUMN IF EXISTS updated_at",
        "ALTER TABLE document DROP COLUMN IF EXISTS created_by",
        "ALTER TABLE document DROP COLUMN IF EXISTS source_type",
        "ALTER TABLE document DROP COLUMN IF EXISTS display_name",
        "DROP TABLE IF EXISTS source_blob",
    )
    for statement in statements:
        op.execute(statement)
