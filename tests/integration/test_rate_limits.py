from fastapi.testclient import TestClient

from operator_api.main import create_app


def test_guest_session_limit_returns_retry_contract(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'guest-limit.db'}",
        limit_overrides={"api": 20, "guest": 1, "mission": 20},
    )
    with TestClient(app) as client:
        assert client.post("/v1/guest-sessions").status_code == 201
        response = client.post("/v1/guest-sessions")
        assert response.status_code == 429
        assert response.json() == {"detail": "Rate limit exceeded. Retry later."}
        assert int(response.headers["Retry-After"]) >= 1
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert response.headers["X-Request-ID"]


def test_mission_mutation_limit_is_workspace_scoped(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'mission-limit.db'}",
        limit_overrides={"api": 50, "guest": 10, "mission": 2},
    )
    with TestClient(app) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "limited-mission"}
        mission = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        )
        assert mission.status_code == 201
        mission_id = mission.json()["id"]
        assert client.post(f"/v1/missions/{mission_id}/start", headers=headers).status_code == 202
        limited = client.post(f"/v1/missions/{mission_id}/cancel", headers=headers)
        assert limited.status_code == 429

        other_token = client.post("/v1/guest-sessions").json()["token"]
        other_headers = {
            "Authorization": f"Bearer {other_token}",
            "Idempotency-Key": "other-workspace",
        }
        assert client.post(
            "/v1/missions",
            headers=other_headers,
            json={"job_url": "https://example.com/jobs/1"},
        ).status_code == 201
