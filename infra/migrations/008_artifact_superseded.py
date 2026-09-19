"""Migration 008: add superseded_by to artifacts for revision tracking."""

from sqlalchemy import text


def upgrade(connection):
    existing = {
        row[1].lower()
        for row in connection.execute(text("PRAGMA table_info(artifacts)")).fetchall()
    }
    if "superseded_by" not in existing:
        connection.execute(
            text("ALTER TABLE artifacts ADD COLUMN superseded_by TEXT REFERENCES artifacts(id)")
        )
