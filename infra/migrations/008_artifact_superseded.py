"""Migration 008: add superseded_by to artifacts for revision tracking."""

from sqlalchemy import inspect, text


def upgrade(connection):
    if connection.dialect.name == "sqlite":
        existing = {
            row[1].lower()
            for row in connection.execute(text("PRAGMA table_info(artifacts)")).fetchall()
        }
    else:
        existing = {
            column["name"].lower() for column in inspect(connection).get_columns("artifacts")
        }
    if "superseded_by" not in existing:
        connection.execute(
            text("ALTER TABLE artifacts ADD COLUMN superseded_by TEXT REFERENCES artifacts(id)")
        )
