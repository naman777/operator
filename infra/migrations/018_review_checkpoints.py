"""Migration 018: explicit profile and imported-job review checkpoints."""

from sqlalchemy import inspect, text


def upgrade(connection):
    profile_columns = {column["name"].lower() for column in inspect(connection).get_columns("profiles")}
    if "reviewed_version" not in profile_columns:
        connection.execute(text("ALTER TABLE profiles ADD COLUMN reviewed_version INTEGER"))
    job_columns = {column["name"].lower() for column in inspect(connection).get_columns("imported_jobs")}
    if "version" not in job_columns:
        connection.execute(text("ALTER TABLE imported_jobs ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
    if "reviewed_version" not in job_columns:
        connection.execute(text("ALTER TABLE imported_jobs ADD COLUMN reviewed_version INTEGER"))
