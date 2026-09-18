"""Apply ordered migrations; run once before starting the PostgreSQL API."""

import importlib.util
import sys
from pathlib import Path
from sqlalchemy import text

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "apps/api"))
from operator_api.db import database  # noqa: E402 - allow running directly from a source checkout

engine, _ = database()
with engine.begin() as connection:
    if engine.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(184209)"))
    connection.execute(
        text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(100) PRIMARY KEY)")
    )
    applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    for file in sorted((root / "infra/migrations").glob("[0-9]*.py")):
        if file.stem in applied:
            continue
        spec = importlib.util.spec_from_file_location(file.stem, file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade(connection)
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"), {"version": file.stem}
        )
        print(f"Applied {file.stem}")
engine.dispose()
