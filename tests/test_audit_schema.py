"""Verify trace purge semantics are encoded directly in the initial migration."""

from pathlib import Path


def testAuditTraceForeignKeyUsesSetNull() -> None:
    """Deleting a trace must preserve the longer-lived audit event."""
    migrationText = Path("migrations/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert "trace_memory_id UUID REFERENCES trace_memory(id) ON DELETE SET NULL" in migrationText
    assert "trace_identifier_hash BYTEA NOT NULL" in migrationText
    assert (
        "raw_query"
        not in migrationText.split("CREATE TABLE audit_log", maxsplit=1)[1].split(
            "CREATE TABLE typed_memory", maxsplit=1
        )[0]
    )
