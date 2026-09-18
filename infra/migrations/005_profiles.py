"""Workspace profiles and source text documents; frozen schema."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
profiles = Table(
    "profiles",
    metadata,
    Column("workspace_id", String, ForeignKey("workspaces.id"), primary_key=True),
    Column("content", JSON, nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
)
documents = Table(
    "profile_documents",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("checksum", String, nullable=False),
    Column("name", String, nullable=False),
    Column("text", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("workspace_id", "checksum"),
)


def upgrade(connection):
    metadata.create_all(connection, tables=[profiles, documents])
