import os
from pathlib import Path
import subprocess
import sys
from sqlalchemy import create_engine, inspect, text


def test_migrations_are_repeatable(tmp_path):
    root = Path(__file__).resolve().parents[2]
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    env = {**os.environ, "DATABASE_URL": url}
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(root / "scripts/migrate.py")], env=env, check=True, capture_output=True
        )
    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) == {
        "workspaces",
        "missions",
        "mission_steps",
        "events",
        "opportunities",
        "applications",
        "schema_migrations",
        "mission_runs",
        "step_outputs",
        "dispatch_commands",
        "stage_history",
        "approvals",
        "artifacts",
        "profiles",
        "profile_documents",
        "imported_jobs",
        "eval_runs",
        "external_actions",
        "model_calls",
        "evidence_chunks",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM schema_migrations")) == 13
        # Verify new columns added by migrations 007 and 008.
        approvals_cols = {r[1].lower() for r in connection.execute(text("PRAGMA table_info(approvals)")).fetchall()}
        assert "workflow_id" in approvals_cols
        assert "risk_level" in approvals_cols
        artifact_cols = {r[1].lower() for r in connection.execute(text("PRAGMA table_info(artifacts)")).fetchall()}
        assert "superseded_by" in artifact_cols
        import_cols = {r[1].lower() for r in connection.execute(text("PRAGMA table_info(imported_jobs)")).fetchall()}
        assert "screenshot" in import_cols
    engine.dispose()


def test_migrations_adopt_existing_local_bootstrap(tmp_path):
    from operator_api.db import Base

    root = Path(__file__).resolve().parents[2]
    url = f"sqlite:///{tmp_path / 'bootstrap.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    subprocess.run(
        [sys.executable, str(root / "scripts/migrate.py")],
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM schema_migrations")) == 13
    engine.dispose()
