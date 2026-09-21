from fastapi.testclient import TestClient
from operator_api.main import create_app
from operator_api import profiles, runtime
from operator_api.db import database


def test_start_fresh_archives_profile_and_restores_without_losing_history(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'archives.db'}")) as client:
        guest = client.post("/v1/guest-sessions?demo=true").json()
        headers = {"Authorization": f"Bearer {guest['token']}", "Idempotency-Key": "archive-mission"}
        other = client.post("/v1/guest-sessions").json()
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        original = client.get("/v1/profile/state", headers=headers).json()
        assert original["profile"]["synthetic"] is True
        receipt = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={"name": "demo-notes.txt", "text": "Worked with Python and SQL on a demo."},
        )
        assert receipt.status_code == 201
        mission = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()
        current = client.get("/v1/profile/state", headers=headers).json()
        assert current["version"] == 1
        assert any(e["document_id"] == receipt.json()["document_id"] for e in current["profile"]["evidence"])

        stale = client.post("/v1/profile/start-fresh?expected_version=0", headers=headers)
        assert stale.status_code == 409
        fresh = client.post("/v1/profile/start-fresh?expected_version=1", headers=headers)
        assert fresh.status_code == 200
        assert fresh.json()["version"] == 2
        assert fresh.json()["profile"]["evidence"] == []
        assert fresh.json()["profile"]["synthetic"] is False
        assert client.get("/v1/workspace", headers=headers).json()["is_demo"] is False
        assert client.get("/v1/demo/jobs", headers=headers).json() == []
        assert client.get(f"/v1/missions/{mission['id']}", headers=headers).status_code == 200

        archives = client.get("/v1/profile/archives", headers=headers).json()
        assert len(archives) == 1
        assert archives[0]["profile_version"] == 1
        assert archives[0]["was_demo"] is True
        archive_id = archives[0]["id"]
        assert client.get("/v1/profile/archives", headers=other_headers).json() == []
        assert (
            client.post(
                f"/v1/profile/archives/{archive_id}/restore?expected_version=0",
                headers=other_headers,
            ).status_code
            == 404
        )

        own = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={"name": "own-notes.txt", "text": "Designed my own FastAPI service."},
        )
        assert own.status_code == 201
        current = client.get("/v1/profile/state", headers=headers).json()
        assert len(current["profile"]["evidence"]) == 1
        assert current["profile"]["evidence"][0]["document_id"] == own.json()["document_id"]
        engine, sessions = database(f"sqlite:///{tmp_path / 'archives.db'}")
        with sessions() as db:
            active = profiles.load(db, guest["workspace"]["id"], runtime.sample_profile)
            ranked = profiles.retrieve(
                db,
                guest["workspace"]["id"],
                active,
                runtime.sample_job("https://example.com/jobs/1").requirements,
            )
            assert ranked.evidence
            assert all(item.document_id == own.json()["document_id"] for item in ranked.evidence)
        engine.dispose()
        restored = client.post(
            f"/v1/profile/archives/{archive_id}/restore?expected_version={current['version']}",
            headers=headers,
        )
        assert restored.status_code == 200
        assert restored.json()["profile"]["synthetic"] is True
        assert any(
            e["document_id"] == receipt.json()["document_id"] for e in restored.json()["profile"]["evidence"]
        )
        assert client.get("/v1/workspace", headers=headers).json()["is_demo"] is True
        assert len(client.get("/v1/profile/archives", headers=headers).json()) == 2
        assert client.get(f"/v1/missions/{mission['id']}", headers=headers).status_code == 200


def test_active_mission_blocks_profile_mode_change(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'active-archive.db'}")) as client:
        guest = client.post("/v1/guest-sessions?demo=true").json()
        headers = {"Authorization": f"Bearer {guest['token']}", "Idempotency-Key": "active-archive"}
        mission = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()
        assert client.post(f"/v1/missions/{mission['id']}/start", headers=headers).status_code == 202
        blocked = client.post("/v1/profile/start-fresh?expected_version=0", headers=headers)
        assert blocked.status_code == 409
        assert client.get("/v1/profile/archives", headers=headers).json() == []
