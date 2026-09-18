"""Stored public job snapshots and typed extraction."""

from sqlalchemy import Column, DateTime, ForeignKey, JSON, MetaData, String, Table, func

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
jobs = Table(
    "imported_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("original_url", String, nullable=False),
    Column("content_hash", String, nullable=False),
    Column("posting", JSON, nullable=False),
    Column("snapshot", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def upgrade(connection):
    metadata.create_all(connection, tables=[jobs])
