"""Migration 009: persisted, workspace-scoped evaluation runs."""

from sqlalchemy import Column, DateTime, ForeignKey, JSON, MetaData, String, Table, func

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
eval_runs = Table(
    "eval_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("dataset_version", String, nullable=False),
    Column("evaluator_version", String, nullable=False),
    Column("metrics", JSON, nullable=False),
    Column("case_results", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def upgrade(connection):
    metadata.create_all(connection, tables=[eval_runs])
