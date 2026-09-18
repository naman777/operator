from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from operator_api.db import DispatchCommand, Event, MissionRun, database
from operator_api.main import create_app
from operator_api.runtime import begin_step, finish_step, fail_mission


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    engine, sessions = database(url)
    with TestClient(create_app(url)) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "runtime-test-0001"}
        mission = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()
        yield client, headers, mission["id"], sessions
    engine.dispose()


def test_concurrent_start_enqueues_exactly_once(setup):
    client, headers, mid, sessions = setup
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: client.post(f"/v1/missions/{mid}/start", headers=headers), range(4))
        )
    assert all(r.status_code == 202 for r in responses)
    with sessions() as db:
        commands = db.scalars(select(DispatchCommand)).all()
        assert len(commands) == 1
        assert commands[0].workflow_id == f"opportunity-{mid}-1"
        assert [e.sequence for e in db.scalars(select(Event).order_by(Event.sequence))] == [1, 2]
    run = client.get(f"/v1/missions/{mid}/run", headers=headers).json()
    assert len(run["steps"]) == 5
    assert all(s["status"] == "pending" for s in run["steps"])


def test_cancel_prevents_late_activity_writes(setup):
    client, headers, mid, sessions = setup
    client.post(f"/v1/missions/{mid}/start", headers=headers)
    begin_step(sessions, mid, 1, "planning")
    assert client.post(f"/v1/missions/{mid}/cancel", headers=headers).status_code == 200
    assert client.post(f"/v1/missions/{mid}/cancel", headers=headers).status_code == 200
    assert finish_step(sessions, mid, 1, "planning", {"test": True}, 1) == {"stopped": True}
    with sessions() as db:
        assert len(db.scalars(select(DispatchCommand)).all()) == 2
    assert client.get(f"/v1/missions/{mid}/run", headers=headers).json()["steps"][0]["status"] == "cancelled"


def test_retry_reuses_completed_checkpoint_and_rejects_stale_run(setup):
    client, headers, mid, sessions = setup
    client.post(f"/v1/missions/{mid}/start", headers=headers)
    begin_step(sessions, mid, 1, "planning")
    finish_step(sessions, mid, 1, "planning", {"plan": "stored"}, 7)
    fail_mission(sessions, mid, 1, "extracting")
    assert client.post(f"/v1/missions/{mid}/retry", headers=headers).status_code == 202
    assert begin_step(sessions, mid, 2, "planning") == {"cached": {"plan": "stored"}}
    assert begin_step(sessions, mid, 1, "extracting") == {"stopped": True}
    run = client.get(f"/v1/missions/{mid}/run", headers=headers).json()
    assert run["run_number"] == 2
    assert run["steps"][0]["attempt"] == 1
    assert run["steps"][0]["latency_ms"] == 7


def test_controls_reject_other_workspaces_and_non_fixture_execution(setup):
    client, headers, mid, sessions = setup
    other = {"Authorization": "Bearer " + client.post("/v1/guest-sessions").json()["token"]}
    for action in ("start", "retry", "cancel", "simulate-failure"):
        assert client.post(f"/v1/missions/{mid}/{action}", headers=other, json={}).status_code == 404
    assert client.get(f"/v1/missions/{mid}/run", headers=other).status_code == 404
    assert client.post(f"/v1/missions/{mid}/retry", headers=headers).status_code == 409
    new = client.post(
        "/v1/missions",
        headers={**headers, "Idempotency-Key": "unsupported-url"},
        json={"job_url": "https://public.example/careers"},
    ).json()
    assert client.post(f"/v1/missions/{new['id']}/start", headers=headers).status_code == 409
    with sessions() as db:
        assert db.scalars(select(DispatchCommand)).all() == []


def test_failure_configuration_is_durable_and_consumed(setup):
    client, headers, mid, sessions = setup
    assert (
        client.post(
            f"/v1/missions/{mid}/simulate-failure", headers=headers, json={"mode": "transient"}
        ).status_code
        == 200
    )
    client.post(f"/v1/missions/{mid}/start", headers=headers)
    assert begin_step(sessions, mid, 1, "matching") == {"simulate_failure": True}
    assert "job_url" in begin_step(sessions, mid, 1, "matching")
    with sessions() as db:
        assert db.get(MissionRun, mid).failure_remaining == 0
