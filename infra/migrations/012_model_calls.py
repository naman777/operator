"""Migration 012: auditable model usage and configured cost."""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, func

metadata = MetaData()
Table("missions", metadata, Column("id", String, primary_key=True))
model_calls = Table(
    "model_calls",
    metadata,
    Column("id", String, primary_key=True),
    Column("mission_id", String, ForeignKey("missions.id"), nullable=False, index=True),
    Column("step", String, nullable=False),
    Column("model", String, nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_usd", Float, nullable=False, default=0),
    Column("status", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def upgrade(connection):
    metadata.create_all(connection, tables=[model_calls])
