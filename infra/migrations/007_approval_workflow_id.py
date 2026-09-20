"""Migration 007: add workflow_id to approvals for Temporal signal routing."""

from sqlalchemy import inspect, text


def upgrade(connection):
    if connection.dialect.name == "sqlite":
        existing = {
            row[1].lower()
            for row in connection.execute(text("PRAGMA table_info(approvals)")).fetchall()
        }
    else:
        existing = {
            column["name"].lower() for column in inspect(connection).get_columns("approvals")
        }
    if "workflow_id" not in existing:
        connection.execute(text("ALTER TABLE approvals ADD COLUMN workflow_id TEXT"))
