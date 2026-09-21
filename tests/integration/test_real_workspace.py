import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from operator_api.db import database
from operator_api.main import create_app
from operator_worker.activities import Activities
from temporalio.testing import ActivityEnvironment


def test_real_workspace_starts_empty_and_uses_only_owned_sources(tmp_path):
    url = f"sqlite:///{tmp_path / 'real-profile.db'}"
    engine, sessions = database(url)
    with TestClient(create_app(url)) as client:
        real = client.post("/v1/guest-sessions").json()
        headers = {"Authorization": f"Bearer {real['token']}", "Idempotency-Key": "real-source-001"}
        assert real["workspace"]["is_demo"] is False
        initial = client.get("/v1/profile/state", headers=headers).json()
        assert initial["version"] == 0
        assert initial["profile"]["id"] == real["workspace"]["id"]
        assert initial["profile"]["name"] == ""
        assert initial["profile"]["graduation_year"] is None
        assert initial["profile"]["evidence"] == []
        assert initial["profile"]["synthetic"] is False
        assert client.get("/v1/demo/jobs", headers=headers).json() == []

        sample = client.post(
            "/v1/missions",
            headers=headers,
            json={"job_url": "https://example.com/jobs/1"},
        ).json()
        blocked = client.post(f"/v1/missions/{sample['id']}/start", headers=headers)
        assert blocked.status_code == 409
        assert "profile" in blocked.json()["detail"]

        receipt = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={"name": "my-project.txt", "text": "Built a Python service with FastAPI."},
        )
        assert receipt.status_code == 201
        state = client.get("/v1/profile/state", headers=headers).json()
        assert len(state["profile"]["evidence"]) == 1
        assert state["profile"]["synthetic"] is False
        assert all(e["document_id"] == receipt.json()["document_id"] for e in state["profile"]["evidence"])
        assert not any("Northstar" in e["text"] for e in state["profile"]["evidence"])
        state["profile"]["name"] = "Casey"
        saved = client.patch(
            "/v1/profile",
            headers=headers,
            json={"expected_version": state["version"], "profile": state["profile"]},
        )
        assert saved.status_code == 200
        blocked = client.post(f"/v1/missions/{sample['id']}/start", headers=headers)
        assert blocked.status_code == 409
        assert "confirm your profile" in blocked.json()["detail"]
        confirmed = client.post(
            f"/v1/profile/confirm?expected_version={saved.json()['version']}",
            headers=headers,
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["reviewed_version"] == confirmed.json()["version"]
        blocked = client.post(f"/v1/missions/{sample['id']}/start", headers=headers)
        assert blocked.status_code == 409
        assert "Import" in blocked.json()["detail"]

        job = {
            "@type": "JobPosting",
            "title": "Backend Engineer",
            "hiringOrganization": {"name": "Example Co"},
            "description": "Build Python services.",
            "skills": ["Python"],
        }
        html = '<script type="application/ld+json">' + json.dumps(job) + "</script>"
        with patch("operator_api.extraction.fetch", return_value=("https://jobs.example/role", html)):
            imported = client.post(
                "/v1/opportunities/import",
                headers=headers,
                json={"url": "https://jobs.example/role"},
            )
        assert imported.status_code == 201
        mission = client.post(
            "/v1/missions",
            headers={**headers, "Idempotency-Key": "real-source-002"},
            json={"job_url": "https://jobs.example/role"},
        ).json()
        blocked = client.post(f"/v1/missions/{mission['id']}/start", headers=headers)
        assert blocked.status_code == 409
        assert "job's requirements" in blocked.json()["detail"]
        review = client.patch(
            f"/v1/opportunities/imports/{imported.json()['import_id']}/review",
            headers=headers,
            json={
                "expected_version": imported.json()["version"],
                "requirements": [
                    {"id": requirement["id"], "importance": requirement["importance"]}
                    for requirement in imported.json()["posting"]["requirements"]
                ],
                "accept_eligibility": True,
            },
        )
        assert review.status_code == 200
        assert review.json()["reviewed_version"] == review.json()["version"]
        assert client.post(f"/v1/missions/{mission['id']}/start", headers=headers).status_code == 202
        planned = ActivityEnvironment().run(
            Activities(sessions).execute_step,
            {"mission_id": mission["id"], "run_number": 1, "step": "planning"},
        )
        assert planned["candidate_profile"]["name"] == "Casey"
        assert planned["candidate_profile"]["synthetic"] is False
        assert planned["candidate_profile"]["graduation_year"] is None
        assert [e["document_id"] for e in planned["candidate_profile"]["evidence"]] == [
            receipt.json()["document_id"]
        ]
        assert planned["execution_mode"] == "public-snapshot"
        outputs = {"planning": planned}
        for step in ("extracting", "researching", "matching", "verifying", "generating"):
            outputs[step] = ActivityEnvironment().run(
                Activities(sessions).execute_step,
                {"mission_id": mission["id"], "run_number": 1, "step": step, "inputs": outputs},
            )
        run = client.get(f"/v1/missions/{mission['id']}/run", headers=headers).json()
        assert run["mission"]["status"] == "completed"
        assert run["execution_mode"] == "public-snapshot"
        assert len(run["result"]["artifact_ids"]) == 4
        artifacts = client.get(f"/v1/missions/{mission['id']}/artifacts", headers=headers).json()
        assert len(artifacts) == 4
        assert all("Northstar" not in json.dumps(artifact) for artifact in artifacts)

        claimed = client.post(
            "/v1/accounts/register",
            headers=headers,
            json={"email": "casey@example.com", "password": "correct-horse-battery"},
        )
        assert claimed.status_code == 201
        assert claimed.json()["workspace"]["is_demo"] is False
        account_headers = {"Authorization": f"Bearer {claimed.json()['token']}"}
        assert client.get("/v1/profile", headers=account_headers).json()["name"] == "Casey"
        assert client.get(f"/v1/missions/{mission['id']}", headers=account_headers).status_code == 200

        demo = client.post("/v1/guest-sessions?demo=true").json()
        demo_headers = {"Authorization": f"Bearer {demo['token']}"}
        assert client.get("/v1/profile", headers=demo_headers).json()["synthetic"] is True
        assert len(client.get("/v1/demo/jobs", headers=demo_headers).json()) == 3
    engine.dispose()
