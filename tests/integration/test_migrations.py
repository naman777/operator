import os
from pathlib import Path
import subprocess
import sys
import pytest
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
        "profile_archives",
        "profile_documents",
        "imported_jobs",
        "eval_runs",
        "external_actions",
        "model_calls",
        "evidence_chunks",
        "accounts",
        "account_sessions",
        "rate_limit_buckets",
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM schema_migrations")) == 20
        # Verify new columns added by migrations 007 and 008.
        approvals_cols = {
            r[1].lower() for r in connection.execute(text("PRAGMA table_info(approvals)")).fetchall()
        }
        assert "workflow_id" in approvals_cols
        assert "risk_level" in approvals_cols
        artifact_cols = {
            r[1].lower() for r in connection.execute(text("PRAGMA table_info(artifacts)")).fetchall()
        }
        assert "superseded_by" in artifact_cols
        import_cols = {
            r[1].lower() for r in connection.execute(text("PRAGMA table_info(imported_jobs)")).fetchall()
        }
        assert "screenshot" in import_cols
        assert {"version", "reviewed_version"} <= import_cols
        profile_cols = {
            r[1].lower() for r in connection.execute(text("PRAGMA table_info(profiles)")).fetchall()
        }
        assert "reviewed_version" in profile_cols
        dispatch_cols = {
            r[1].lower() for r in connection.execute(text("PRAGMA table_info(dispatch_commands)")).fetchall()
        }
        assert "dead_lettered_at" in dispatch_cols
        workspace_cols = {
            r[1].lower() for r in connection.execute(text("PRAGMA table_info(workspaces)")).fetchall()
        }
        assert "account_id" in workspace_cols
        assert "user_agent" in {c["name"] for c in inspect(connection).get_columns("account_sessions")}
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
        assert connection.scalar(text("SELECT COUNT(*) FROM schema_migrations")) == 20
    engine.dispose()


@pytest.mark.skipif(
    not os.getenv("OPERATOR_TEST_POSTGRES_URL"),
    reason="Set OPERATOR_TEST_POSTGRES_URL to test fresh PostgreSQL migrations",
)
def test_migrations_on_fresh_postgresql():
    root = Path(__file__).resolve().parents[2]
    url = os.environ["OPERATOR_TEST_POSTGRES_URL"]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/migrate.py")],
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Applied 007_approval_workflow_id" in result.stdout
    assert "Applied 008_artifact_superseded" in result.stdout

    engine = create_engine(url)
    inspector = inspect(engine)
    assert "approvals" in inspector.get_table_names()
    assert "artifacts" in inspector.get_table_names()
    assert "workflow_id" in {column["name"] for column in inspector.get_columns("approvals")}
    assert "superseded_by" in {column["name"] for column in inspector.get_columns("artifacts")}
    assert "reviewed_version" in {column["name"] for column in inspector.get_columns("profiles")}
    assert {"version", "reviewed_version"} <= {
        column["name"] for column in inspector.get_columns("imported_jobs")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM schema_migrations")) == 20
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    engine.dispose()
