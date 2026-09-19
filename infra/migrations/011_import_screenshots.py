"""Migration 011: optional browser-rendered job screenshot."""

from sqlalchemy import inspect, text


def upgrade(connection):
    columns = {column["name"].lower() for column in inspect(connection).get_columns("imported_jobs")}
    if "screenshot" not in columns:
        blob_type = "BYTEA" if connection.dialect.name == "postgresql" else "BLOB"
        connection.execute(text(f"ALTER TABLE imported_jobs ADD COLUMN screenshot {blob_type}"))
