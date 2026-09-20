from fastapi.testclient import TestClient

from operator_api.main import create_app


def test_account_claim_login_logout_and_workspace_isolation(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'accounts.db'}")) as client:
        guest = client.post("/v1/guest-sessions").json()
        guest_headers = {"Authorization": f"Bearer {guest['token']}"}
        mission = client.post(
            "/v1/missions",
            headers={**guest_headers, "Idempotency-Key": "account-mission"},
            json={"job_url": "https://example.com/jobs/1"},
        ).json()
        credentials = {"email": "Owner@Example.com", "password": "correct-horse-battery"}
        registered = client.post(
            "/v1/accounts/register", headers=guest_headers, json=credentials
        )
        assert registered.status_code == 201
        account_session = registered.json()
        assert account_session["account"]["email"] == "owner@example.com"
        assert account_session["workspace"]["id"] == guest["workspace"]["id"]
        assert client.get("/v1/missions", headers=guest_headers).status_code == 401

        headers = {"Authorization": f"Bearer {account_session['token']}"}
        assert client.get(f"/v1/missions/{mission['id']}", headers=headers).status_code == 200
        assert client.post("/v1/accounts/logout", headers=headers).status_code == 204
        assert client.get("/v1/missions", headers=headers).status_code == 401

        bad = client.post(
            "/v1/accounts/login",
            json={**credentials, "password": "incorrect-password"},
        )
        assert bad.status_code == 401
        login = client.post("/v1/accounts/login", json=credentials)
        assert login.status_code == 200
        restored = {"Authorization": f"Bearer {login.json()['token']}"}
        assert client.get(f"/v1/missions/{mission['id']}", headers=restored).status_code == 200


def test_account_validation_and_duplicate_email(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'account-validation.db'}")) as client:
        first = client.post("/v1/guest-sessions").json()
        headers = {"Authorization": f"Bearer {first['token']}"}
        assert client.post(
            "/v1/accounts/register",
            headers=headers,
            json={"email": "invalid", "password": "long-enough-password"},
        ).status_code == 422
        credentials = {"email": "person@example.com", "password": "long-enough-password"}
        assert client.post("/v1/accounts/register", headers=headers, json=credentials).status_code == 201
        second = client.post("/v1/guest-sessions").json()
        second_headers = {"Authorization": f"Bearer {second['token']}"}
        assert client.post(
            "/v1/accounts/register", headers=second_headers, json=credentials
        ).status_code == 409
