"""Integration tests for application pipeline and approval inbox endpoints."""

from fastapi.testclient import TestClient
from operator_api.main import create_app


def make_client(tmp_path, name="test"):
    return TestClient(create_app(f"sqlite:///{tmp_path / f'{name}.db'}"))


def test_applications_empty_on_fresh_workspace(tmp_path):
    with make_client(tmp_path, "app_empty") as client:
        token = client.post("/v1/guest-sessions?demo=true").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/v1/applications", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == []


def test_guest_session_includes_expiry(tmp_path):
    with make_client(tmp_path, "expiry") as client:
        data = client.post("/v1/guest-sessions?demo=true").json()
        assert "expires_at" in data["workspace"]
        assert data["workspace"]["expires_at"] is not None


def test_approvals_empty_and_auth_required(tmp_path):
    with make_client(tmp_path, "approvals") as client:
        token = client.post("/v1/guest-sessions?demo=true").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/v1/approvals", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == []
        assert client.get("/v1/approvals").status_code == 401


def test_guest_session_reset_issues_new_token(tmp_path):
    with make_client(tmp_path, "reset") as client:
        original = client.post("/v1/guest-sessions?demo=true").json()["token"]
        orig_headers = {"Authorization": f"Bearer {original}"}
        reset = client.post("/v1/guest-sessions/reset", headers=orig_headers).json()
        new_token = reset["token"]
        assert new_token != original
        # New token works.
        assert (
            client.get("/v1/workspace", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
        )
        # Old token is now invalidated.
        assert client.get("/v1/workspace", headers=orig_headers).status_code == 401


def test_application_stage_patch(tmp_path):
    """Seed an application manually and test the PATCH stage endpoint."""
    from uuid import uuid4
    from operator_api.db import Application, Opportunity, database, utcnow

    db_url = f"sqlite:///{tmp_path / 'stage.db'}"
    with make_client(tmp_path, "stage") as client:
        token = client.post("/v1/guest-sessions?demo=true").json()["token"]
        ws_data = client.get("/v1/workspace", headers={"Authorization": f"Bearer {token}"}).json()
        ws_id = ws_data["id"]
        headers = {"Authorization": f"Bearer {token}"}

        # Seed via DB directly.
        _, sessions = database(db_url)
        with sessions.begin() as db:
            opp = Opportunity(
                id=str(uuid4()),
                workspace_id=ws_id,
                title="Software Engineer",
                company="Acme Corp",
                url="https://acme.example/jobs/swe",
            )
            db.add(opp)
            db.flush()
            app = Application(
                id=str(uuid4()),
                workspace_id=ws_id,
                opportunity_id=opp.id,
                stage="saved",
                company="Acme Corp",
                title="Software Engineer",
                job_url="https://acme.example/jobs/swe",
                updated_at=utcnow(),
            )
            db.add(app)
            app_id = app.id

        # List applications: should contain one.
        apps = client.get("/v1/applications", headers=headers).json()
        assert len(apps) == 1
        assert apps[0]["stage"] == "saved"

        # Patch stage to applied.
        resp = client.patch(
            f"/v1/applications/{app_id}",
            headers=headers,
            json={"stage": "applied", "note": "Submitted via portal"},
        )
        assert resp.status_code == 200
        assert resp.json()["stage"] == "applied"

        # Invalid stage should fail.
        assert (
            client.patch(
                f"/v1/applications/{app_id}",
                headers=headers,
                json={"stage": "hired"},
            ).status_code
            == 422
        )

        # Other workspace cannot access.
        other = client.post("/v1/guest-sessions?demo=true").json()["token"]
        assert (
            client.patch(
                f"/v1/applications/{app_id}",
                headers={"Authorization": f"Bearer {other}"},
                json={"stage": "interview"},
            ).status_code
            == 404
        )
