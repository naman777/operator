"""Migration 019: optional browser label for account session management."""

from sqlalchemy import inspect, text


def upgrade(connection):
    columns = {column["name"].lower() for column in inspect(connection).get_columns("account_sessions")}
    if "user_agent" not in columns:
        connection.execute(text("ALTER TABLE account_sessions ADD COLUMN user_agent VARCHAR(512)"))
