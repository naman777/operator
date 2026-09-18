"""Versioned artifact drafts; frozen schema compatible with SQLite and PostgreSQL."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, MetaData, String, Table, func

metadata = MetaData()
Table("missions", metadata, Column("id", String, primary_key=True))
Table("workspaces", metadata, Column("id", String, primary_key=True))
artifacts = Table(
    "artifacts",
    metadata,
    Column("id", String, primary_key=True),
    Column("mission_id", String, ForeignKey("missions.id"), nullable=False, index=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("type", String, nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("content", JSON, nullable=False),
    Column("status", String, nullable=False, server_default="draft"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
version_index = Index(
    "ix_artifacts_mission_type_version",
    artifacts.c.mission_id,
    artifacts.c.type,
    artifacts.c.version,
    unique=True,
)


def upgrade(connection):
    metadata.create_all(connection, tables=[artifacts])
    version_index.create(connection, checkfirst=True)
