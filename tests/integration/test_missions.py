from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest
from operator_api.main import create_app


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def client(database_url):
    with TestClient(create_app(database_url)) as client:
        yield client


def guest(client):
    response = client.post("/v1/guest-sessions")
    assert response.status_code == 201
    return {"Authorization": "Bearer " + response.json()["token"]}


def create(client, headers, key="mission-key-123", **overrides):
    return client.post(
        "/v1/missions",
        headers={**headers, "Idempotency-Key": key},
        json={"job_url": "https://example.com/jobs/1", **overrides},
    )


def test_persistence_events_and_workspace_isolation(client, database_url):
    alice, bob = guest(client), guest(client)
    response = create(client, alice)
    assert response.status_code == 201
    mission = response.json()
    assert mission["status"] == "draft"
    path = f"/v1/missions/{mission['id']}"
    assert client.get(path, headers=bob).status_code == 404
    assert client.get(path + "/events", headers=bob).status_code == 404
    assert client.get("/v1/missions", headers=bob).json() == []
    events = client.get(path + "/events", headers=alice).json()
    assert [event["sequence"] for event in events] == [1]
    assert events[0]["type"] == "mission.created"
    assert client.get(path + "/events?after=1", headers=alice).json() == []
    with TestClient(create_app(database_url)) as restarted:
        assert restarted.get(path, headers=alice).json()["id"] == mission["id"]


def test_idempotent_requests_and_conflict(client):
    headers = guest(client)
    first = create(client, headers)
    second = create(client, headers)
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/v1/missions", headers=headers).json()) == 1
    assert create(client, headers, job_url="https://example.com/jobs/2").status_code == 409


def test_concurrent_duplicate_creation(client):
    headers = guest(client)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: create(client, headers), range(4)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201]
    assert len({r.json()["id"] for r in responses}) == 1
    mission_id = responses[0].json()["id"]
    assert len(client.get(f"/v1/missions/{mission_id}/events", headers=headers).json()) == 1


def test_auth_validation_and_request_ids(client):
    assert client.get("/v1/missions").status_code == 401
    assert client.get("/v1/missions", headers={"Authorization": "Bearer invalid"}).status_code == 401
    headers = guest(client)
    assert create(client, headers, job_url="file:///etc/passwd").status_code == 422
    assert create(client, headers, budget_usd=11).status_code == 422
    assert create(client, headers, budget_usd=0).status_code == 422
    assert create(client, headers, workspace_id="someone-else").status_code == 422
    assert (
        client.post("/v1/missions", headers=headers, json={"job_url": "https://example.com"}).status_code
        == 422
    )
    assert client.get("/health").headers["X-Request-ID"]
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["status"] == "ok"


def test_seed_contracts(client):
    headers = guest(client)
    profile = client.get("/v1/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["synthetic"] is True
    jobs = client.get("/v1/demo/jobs", headers=headers).json()
    assert len(jobs) == 3
    for job in jobs:
        assert job["synthetic"]
        sources = {s["id"] for s in job["sources"]}
        assert all(r["source_id"] in sources for r in job["requirements"])
