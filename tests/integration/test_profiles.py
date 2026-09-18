from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from operator_api.main import create_app


def test_ingestion_corrections_isolation_and_conflicts(tmp_path):
    url = f"sqlite:///{tmp_path / 'profile.db'}"
    with TestClient(create_app(url)) as client:

        def guest():
            return {"Authorization": "Bearer " + client.post("/v1/guest-sessions").json()["token"]}

        headers, other = guest(), guest()
        document = {
            "name": "resume.txt",
            "text": "Built a Python and FastAPI service.\nDeployed it with Docker.",
        }
        with ThreadPoolExecutor(max_workers=3) as executor:
            receipts = list(
                executor.map(
                    lambda _: client.post("/v1/profile/documents", headers=headers, json=document).json(),
                    range(3),
                )
            )
        assert len({r["document_id"] for r in receipts}) == 1
        state = client.get("/v1/profile/state", headers=headers).json()
        assert state["version"] == 1
        chunks = [e for e in state["profile"]["evidence"] if e["document_id"] == receipts[0]["document_id"]]
        assert len(chunks) == 2
        assert chunks[0]["text"] == "Built a Python and FastAPI service."
        assert "line 1" in chunks[0]["source_location"]
        assert "FastAPI" in chunks[0]["skills"]
        assert len(client.get("/v1/evidence", headers=other).json()) == 2
        state["profile"]["name"] = "My corrected name"
        body = {"expected_version": 1, "profile": state["profile"]}
        assert client.patch("/v1/profile", headers=headers, json=body).json()["version"] == 2
        assert client.patch("/v1/profile", headers=headers, json=body).status_code == 409
        body["expected_version"] = 2
        body["profile"]["evidence"][0]["text"] = "Fabricated achievement"
        assert client.patch("/v1/profile", headers=headers, json=body).status_code == 422
        assert (
            client.post(
                "/v1/profile/documents", headers=headers, json={"name": "blank", "text": " " * 20}
            ).status_code
            == 422
        )
        assert client.post("/v1/profile/documents", json=document).status_code == 401
    with TestClient(create_app(url)) as restarted:
        assert restarted.get("/v1/profile", headers=headers).json()["name"] == "My corrected name"


def test_workflow_profile_snapshot_is_stable_after_corrections(tmp_path):
    from temporalio.testing import ActivityEnvironment
    from operator_api.db import database
    from operator_worker.activities import Activities

    url = f"sqlite:///{tmp_path / 'snapshot.db'}"
    engine, sessions = database(url)
    with TestClient(create_app(url)) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "snapshot-test-001"}
        state = client.get("/v1/profile/state", headers=headers).json()
        state["profile"]["name"] = "Before run"
        client.patch(
            "/v1/profile", headers=headers, json={"expected_version": 0, "profile": state["profile"]}
        )
        mid = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()["id"]
        client.post(f"/v1/missions/{mid}/start", headers=headers)
        activities = Activities(sessions)
        planning = ActivityEnvironment().run(
            activities.execute_step, {"mission_id": mid, "run_number": 1, "step": "planning"}
        )
        state["profile"]["name"] = "After run"
        client.patch(
            "/v1/profile", headers=headers, json={"expected_version": 1, "profile": state["profile"]}
        )
        extraction = ActivityEnvironment().run(
            activities.execute_step,
            {"mission_id": mid, "run_number": 1, "step": "extracting", "inputs": {"planning": planning}},
        )
        matched = ActivityEnvironment().run(
            activities.execute_step,
            {
                "mission_id": mid,
                "run_number": 1,
                "step": "matching",
                "inputs": {"planning": planning, "extracting": extraction},
            },
        )
        assert matched["profile"]["name"] == "Before run"
        assert client.get("/v1/profile", headers=headers).json()["name"] == "After run"
    engine.dispose()
