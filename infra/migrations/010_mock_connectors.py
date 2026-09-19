"""Migration 010: approval risk classification and idempotent mock actions."""

from sqlalchemy import Column, DateTime, ForeignKey, JSON, MetaData, String, Table, func, inspect, text

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
Table("missions", metadata, Column("id", String, primary_key=True))
Table("approvals", metadata, Column("id", String, primary_key=True))
actions = Table(
    "external_actions",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("mission_id", String, ForeignKey("missions.id"), nullable=False, index=True),
    Column("approval_id", String, ForeignKey("approvals.id"), nullable=False, unique=True),
    Column("type", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("provider", String, nullable=False, server_default="mock"),
    Column("status", String, nullable=False, server_default="created"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def upgrade(connection):
    columns = {column["name"].lower() for column in inspect(connection).get_columns("approvals")}
    if "risk_level" not in columns:
        connection.execute(text("ALTER TABLE approvals ADD COLUMN risk_level TEXT DEFAULT 'medium' NOT NULL"))
    metadata.create_all(connection, tables=[actions])
