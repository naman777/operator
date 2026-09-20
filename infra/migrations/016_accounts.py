"""Migration 016: persistent accounts and revocable workspace sessions."""

from sqlalchemy import Column, DateTime, ForeignKey, MetaData, String, Table, inspect, text

metadata = MetaData()
Table("workspaces", metadata, Column("id", String, primary_key=True))
accounts = Table(
    "accounts",
    metadata,
    Column("id", String, primary_key=True),
    Column("email", String, nullable=False, unique=True, index=True),
    Column("password_hash", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
sessions = Table(
    "account_sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", String, ForeignKey("accounts.id"), nullable=False, index=True),
    Column("workspace_id", String, ForeignKey("workspaces.id"), nullable=False, index=True),
    Column("token_hash", String, nullable=False, unique=True, index=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def upgrade(connection):
    metadata.create_all(connection, tables=[accounts])
    columns = {column["name"].lower() for column in inspect(connection).get_columns("workspaces")}
    if "account_id" not in columns:
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN account_id VARCHAR REFERENCES accounts(id)"))
    metadata.create_all(connection, tables=[sessions])
