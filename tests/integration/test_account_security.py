import hashlib
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from operator_api.db import AccountSession, Workspace, database, utcnow
from operator_api.main import create_app


def test_session_controls_and_password_change(tmp_path):
    url = f"sqlite:///{tmp_path / 'security.db'}"
    with TestClient(create_app(url)) as client:

        def register(email):
            guest = client.post("/v1/guest-sessions").json()
            credentials = {"email": email, "password": "correct-horse-battery"}
            result = client.post(
                "/v1/accounts/register",
                json=credentials,
                headers={"Authorization": f"Bearer {guest['token']}", "User-Agent": "Browser A"},
            )
            assert result.status_code == 201
            return credentials, {"Authorization": f"Bearer {result.json()['token']}"}

        credentials, first = register("owner@example.com")
        _, stranger = register("stranger@example.com")
        login = client.post("/v1/accounts/login", json=credentials, headers={"User-Agent": "Browser B"})
        second = {"Authorization": f"Bearer {login.json()['token']}"}
        response = client.get("/v1/accounts/sessions", headers=first)
        assert "no-store" in response.headers["cache-control"]
        rows = response.json()
        assert len(rows) == 2
        assert sum(row["current"] for row in rows) == 1
        assert {row["user_agent"] for row in rows} == {"Browser A", "Browser B"}
        assert all(
            set(row) == {"id", "user_agent", "created_at", "expires_at", "current", "schema_version"}
            for row in rows
        )
        target = next(row["id"] for row in rows if not row["current"])
        assert client.delete(f"/v1/accounts/sessions/{target}", headers=stranger).status_code == 404
        assert client.post("/v1/guest-sessions/reset", headers=first).status_code == 403
        assert client.delete(f"/v1/accounts/sessions/{target}", headers=first).status_code == 204
        assert client.delete(f"/v1/accounts/sessions/{target}", headers=first).status_code == 204
        assert client.get("/v1/workspace", headers=second).status_code == 401
        login = client.post("/v1/accounts/login", json=credentials)
        second = {"Authorization": f"Bearer {login.json()['token']}"}
        assert client.post("/v1/accounts/sessions/revoke-others", headers=first).status_code == 204
        assert client.get("/v1/workspace", headers=second).status_code == 401
        assert client.get("/v1/workspace", headers=stranger).status_code == 200
        body = {"current_password": "incorrect-password", "new_password": "replacement-password"}
        assert client.post("/v1/accounts/password", headers=first, json=body).status_code == 403
        assert client.get("/v1/workspace", headers=first).status_code == 200
        login = client.post("/v1/accounts/login", json=credentials)
        second = {"Authorization": f"Bearer {login.json()['token']}"}
        body["current_password"] = credentials["password"]
        assert client.post("/v1/accounts/password", headers=first, json=body).status_code == 204
        assert client.get("/v1/workspace", headers=first).status_code == 401
        assert client.get("/v1/workspace", headers=second).status_code == 401
        assert client.post("/v1/accounts/login", json=credentials).status_code == 401
        credentials["password"] = body["new_password"]
        login = client.post("/v1/accounts/login", json=credentials)
        assert login.status_code == 200
        active = {"Authorization": f"Bearer {login.json()['token']}"}
        engine, sessions = database(url)
        with sessions() as db:
            row = db.scalar(
                select(AccountSession).where(
                    AccountSession.revoked_at.is_(None), AccountSession.user_agent == "testclient"
                )
            )
            row.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        assert client.get("/v1/accounts/sessions", headers=active).status_code == 401
        engine.dispose()


def test_guests_cannot_manage_account_sessions(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'guest.db'}")) as client:
        guest = client.post("/v1/guest-sessions").json()
        headers = {"Authorization": f"Bearer {guest['token']}"}
        assert client.get("/v1/accounts/sessions", headers=headers).status_code == 403
        assert client.delete("/v1/accounts/sessions/unknown", headers=headers).status_code == 403
        assert client.post("/v1/accounts/sessions/revoke-others", headers=headers).status_code == 403
        assert client.get("/v1/accounts/sessions").status_code == 401


def test_account_rejects_legacy_guest_credential_and_can_revoke_current(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    with TestClient(create_app(url)) as client:
        guest = client.post("/v1/guest-sessions").json()
        guest_headers = {"Authorization": f"Bearer {guest['token']}"}
        registered = client.post(
            "/v1/accounts/register",
            headers=guest_headers,
            json={"email": "owner@example.com", "password": "correct-horse-battery"},
        )
        assert registered.status_code == 201
        headers = {"Authorization": f"Bearer {registered.json()['token']}"}
        engine, sessions = database(url)
        with sessions() as db:
            workspace = db.get(Workspace, guest["workspace"]["id"])
            workspace.token_hash = hashlib.sha256(guest["token"].encode()).hexdigest()
            db.commit()
        assert client.get("/v1/workspace", headers=guest_headers).status_code == 401
        row = client.get("/v1/accounts/sessions", headers=headers).json()[0]
        assert client.delete(f"/v1/accounts/sessions/{row['id']}", headers=headers).status_code == 204
        assert client.get("/v1/workspace", headers=headers).status_code == 401
        engine.dispose()
