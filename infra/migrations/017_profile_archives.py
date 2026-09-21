"""Migration 017: preserve profile snapshots before an explicit start-fresh action."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, MetaData, String, Table

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
archives = Table(
    "profile_archives",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("content", JSON, nullable=False),
    Column("profile_version", Integer, nullable=False),
    Column("was_demo", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def upgrade(connection):
    metadata.create_all(connection, tables=[archives])
