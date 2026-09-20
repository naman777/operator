"""Migration 015: terminal state for exhausted workflow dispatch commands."""

from sqlalchemy import inspect, text


def upgrade(connection):
    columns = {column["name"].lower() for column in inspect(connection).get_columns("dispatch_commands")}
    if "dead_lettered_at" not in columns:
        connection.execute(text("ALTER TABLE dispatch_commands ADD COLUMN dead_lettered_at TIMESTAMP"))
