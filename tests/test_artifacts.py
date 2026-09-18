from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from temporalio.testing import ActivityEnvironment
from operator_api.main import create_app
from operator_api.runtime import begin_step, finish_step
from operator_api.db import Application, Artifact, MissionRun, Opportunity, database
from operator_worker.activities import Activities


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    engine, sessions = database(url)
    with TestClient(create_app(url)) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "artifacts-test-0001"}
        mission = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()
        yield client, headers, mission["id"], sessions
    engine.dispose()


def prepare(client, headers, mid, sessions):
    assert client.post(f"/v1/missions/{mid}/start", headers=headers).status_code == 202
    outputs = {}
    for name in ("planning", "extracting", "matching", "verifying"):
        outputs[name] = ActivityEnvironment().run(
            Activities(sessions).execute_step,
            {"mission_id": mid, "run_number": 1, "step": name, "inputs": outputs},
        )
    return outputs


def generate(mid, sessions, inputs):
    return ActivityEnvironment().run(
        Activities(sessions).execute_step,
        {"mission_id": mid, "run_number": 1, "step": "generating", "inputs": inputs},
    )


def test_artifacts_generation_provenance_and_isolation(setup):
    client, headers, mid, sessions = setup
    inputs = prepare(client, headers, mid, sessions)
    result = generate(mid, sessions, inputs)
    run = client.get(f"/v1/missions/{mid}/run", headers=headers).json()
    assert run["mission"]["status"] == "completed"
    data = client.get(f"/v1/missions/{mid}/artifacts", headers=headers).json()
    assert len(data) == 4
    assert {a["id"] for a in data} == set(result["artifact_ids"]) == set(run["result"]["artifact_ids"])
    assert all(a["version"] == 1 and a["status"] == "draft" for a in data)
    assert {a["type"] for a in data} == {
        "cover_letter",
        "resume_suggestions",
        "recruiter_message",
        "interview_brief",
    }
    cover = next(a for a in data if a["type"] == "cover_letter")
    assert "Alex Morgan" in cover["content"]["text"]
    assert "Northstar" in cover["content"]["text"]
    assert "Unknown" not in cover["content"]["text"]
    evidence = {e["id"]: e for e in inputs["matching"]["profile"]["evidence"]}
    for item in data:
        assert item["content"]["needs_review"]
        assert "40%" not in str(item["content"])
        for citation in item["content"]["citations"]:
            if citation["kind"] == "candidate":
                assert citation["excerpt"] == evidence[citation["reference_id"]]["text"]
                assert citation["document_id"] == "resume-demo-v1"
    applications = client.get("/v1/applications", headers=headers).json()
    assert applications[0]["company"] == "Northstar"
    assert applications[0]["title"] == inputs["extracting"]["title"]
    assert client.get(f"/v1/artifacts/{data[0]['id']}", headers=headers).status_code == 200
    other = {"Authorization": "Bearer " + client.post("/v1/guest-sessions").json()["token"]}
    assert client.get(f"/v1/missions/{mid}/artifacts", headers=other).status_code == 404
    assert client.get(f"/v1/artifacts/{data[0]['id']}", headers=other).status_code == 404
    assert client.get(f"/v1/artifacts/{data[0]['id']}").status_code == 401


def test_completion_acknowledgement_replay_does_not_duplicate_artifacts(setup):
    client, headers, mid, sessions = setup
    inputs = prepare(client, headers, mid, sessions)
    result = generate(mid, sessions, inputs)
    assert begin_step(sessions, mid, 1, "generating") == {"cached": result}
    assert finish_step(sessions, mid, 1, "generating", result, 1) == result
    assert generate(mid, sessions, inputs) == result
    with sessions() as db:
        assert len(db.scalars(select(Artifact)).all()) == 4
        assert len(db.scalars(select(Application)).all()) == 1


def test_invalid_final_result_cannot_commit_partial_artifacts(setup):
    from operator_worker.analysis import result

    client, headers, mid, sessions = setup
    inputs = prepare(client, headers, mid, sessions)
    payload = result(mid, inputs["matching"], inputs["verifying"])
    payload["score"] = 1
    with pytest.raises(ValueError, match="stored analysis"):
        finish_step(sessions, mid, 1, "generating", payload, 1)
    with sessions() as db:
        assert db.scalars(select(Artifact)).all() == []
        assert db.scalars(select(Application)).all() == []
        assert db.get(MissionRun, mid).result is None


def test_concurrent_missions_share_workspace_application_but_not_artifacts(setup):
    client, headers, first, sessions = setup
    second = client.post(
        "/v1/missions",
        headers={**headers, "Idempotency-Key": "another-artifact-run"},
        json={"job_url": "https://example.com/jobs/1"},
    ).json()["id"]
    inputs = {mid: prepare(client, headers, mid, sessions) for mid in (first, second)}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda mid: generate(mid, sessions, inputs[mid]), (first, second)))
    assert not set(results[0]["artifact_ids"]) & set(results[1]["artifact_ids"])
    with sessions() as db:
        assert len(db.scalars(select(Application)).all()) == 1
        assert len(db.scalars(select(Opportunity)).all()) == 1
        assert len(db.scalars(select(Artifact)).all()) == 8
    other = {
        "Authorization": "Bearer " + client.post("/v1/guest-sessions").json()["token"],
        "Idempotency-Key": "other-workspace-mission",
    }
    third = client.post("/v1/missions", headers=other, json={"job_url": "https://example.com/jobs/1"}).json()[
        "id"
    ]
    generate(third, sessions, prepare(client, other, third, sessions))
    with sessions() as db:
        assert len(db.scalars(select(Opportunity)).all()) == 2
        assert len(db.scalars(select(Application)).all()) == 2
