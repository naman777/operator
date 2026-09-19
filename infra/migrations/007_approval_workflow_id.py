"""Migration 007: add workflow_id to approvals for Temporal signal routing."""

from sqlalchemy import text


def upgrade(connection):
    existing = {
        row[1].lower()
        for row in connection.execute(text("PRAGMA table_info(approvals)")).fetchall()
    }
    if "workflow_id" not in existing:
        connection.execute(text("ALTER TABLE approvals ADD COLUMN workflow_id TEXT"))
