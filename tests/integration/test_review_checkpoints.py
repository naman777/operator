import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from operator_api.main import create_app


def test_review_versions_scope_and_source_preservation(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'reviews.db'}")) as client:
        owner = client.post("/v1/guest-sessions").json()
        other = client.post("/v1/guest-sessions").json()
        headers = {
            "Authorization": f"Bearer {owner['token']}",
            "Idempotency-Key": "review-mission-001",
        }
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        state = client.get("/v1/profile/state", headers=headers).json()
        assert state["reviewed_version"] is None
        assert client.post("/v1/profile/confirm?expected_version=1", headers=headers).status_code == 409

        first_document = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={"name": "resume.txt", "text": "Built Python and SQL services."},
        )
        assert first_document.status_code == 201
        state = client.get("/v1/profile/state", headers=headers).json()
        state["profile"]["name"] = "Casey"
        saved = client.patch(
            "/v1/profile",
            headers=headers,
            json={"expected_version": state["version"], "profile": state["profile"]},
        ).json()
        confirmed = client.post(
            f"/v1/profile/confirm?expected_version={saved['version']}", headers=headers
        ).json()
        assert confirmed["reviewed_version"] == confirmed["version"]
        assert client.get("/v1/profile/state", headers=other_headers).json()["reviewed_version"] is None

        later_document = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={"name": "new-project.txt", "text": "Designed a FastAPI tool."},
        )
        assert later_document.status_code == 201
        changed = client.get("/v1/profile/state", headers=headers).json()
        assert changed["reviewed_version"] != changed["version"]
        assert (
            client.post(
                f"/v1/profile/confirm?expected_version={confirmed['version']}", headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/v1/profile/confirm?expected_version={changed['version']}", headers=headers
            ).status_code
            == 200
        )

        job = {
            "@type": "JobPosting",
            "title": "Backend Engineer",
            "hiringOrganization": {"name": "Example Co"},
            "description": "Build Python and SQL services.",
            "skills": ["Python", "SQL"],
        }
        html = '<script type="application/ld+json">' + json.dumps(job) + "</script>"
        with patch("operator_api.extraction.fetch", return_value=("https://jobs.example/role", html)):
            imported = client.post(
                "/v1/opportunities/import",
                headers=headers,
                json={"url": "https://jobs.example/role"},
            ).json()
        assert imported["version"] == 1
        assert imported["reviewed_version"] is None
        mission = client.post(
            "/v1/missions",
            headers=headers,
            json={"job_url": "https://jobs.example/role"},
        ).json()
        assert client.post(f"/v1/missions/{mission['id']}/start", headers=headers).status_code == 409

        review_url = f"/v1/opportunities/imports/{imported['import_id']}/review"
        invalid = client.patch(
            review_url,
            headers=headers,
            json={
                "expected_version": 1,
                "requirements": [{"id": "made-up", "importance": "required"}],
            },
        )
        assert invalid.status_code == 422
        assert (
            client.patch(
                review_url,
                headers=other_headers,
                json={"expected_version": 1, "requirements": []},
            ).status_code
            == 404
        )
        original_source = imported["posting"]["sources"]
        first = imported["posting"]["requirements"][0]
        reviewed = client.patch(
            review_url,
            headers=headers,
            json={
                "expected_version": 1,
                "requirements": [{"id": first["id"], "importance": "preferred"}],
                "accept_eligibility": False,
            },
        )
        assert reviewed.status_code == 200
        output = reviewed.json()
        assert output["version"] == output["reviewed_version"] == 2
        assert output["snapshot_sha256"] == imported["snapshot_sha256"]
        assert output["posting"]["sources"] == original_source
        assert output["posting"]["requirements"] == [{**first, "importance": "preferred"}]
        assert (
            client.patch(
                review_url,
                headers=headers,
                json={"expected_version": 1, "requirements": []},
            ).status_code
            == 409
        )
        listed = client.get("/v1/opportunities/imports", headers=headers).json()
        assert listed[0]["posting"]["requirements"] == output["posting"]["requirements"]
        assert client.post(f"/v1/missions/{mission['id']}/start", headers=headers).status_code == 202
        second = client.post(
            "/v1/missions",
            headers={**headers, "Idempotency-Key": "review-mission-002"},
            json={"job_url": "https://jobs.example/role"},
        ).json()
        with patch("operator_api.extraction.fetch", return_value=("https://jobs.example/role", html)):
            newer = client.post(
                "/v1/opportunities/import",
                headers=headers,
                json={"url": "https://jobs.example/role"},
            ).json()
        assert newer["reviewed_version"] is None
        assert newer["snapshot_sha256"] == imported["snapshot_sha256"]
        changed_html = html.replace("SQL", "Go")
        with patch("operator_api.extraction.fetch", return_value=("https://jobs.example/role", changed_html)):
            changed_import = client.post(
                "/v1/opportunities/import",
                headers=headers,
                json={"url": "https://jobs.example/role"},
            ).json()
        assert changed_import["snapshot_sha256"] != imported["snapshot_sha256"]
        assert [
            item["snapshot_sha256"]
            for item in client.get("/v1/opportunities/imports", headers=headers).json()[:3]
        ] == [
            changed_import["snapshot_sha256"],
            newer["snapshot_sha256"],
            imported["snapshot_sha256"],
        ]
        blocked = client.post(f"/v1/missions/{second['id']}/start", headers=headers)
        assert blocked.status_code == 409
        assert "requirements" in blocked.json()["detail"]


def test_expired_real_posting_cannot_start_even_after_review(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'expired.db'}")) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "expired-job-001"}
        assert (
            client.post(
                "/v1/profile/documents",
                headers=headers,
                json={"name": "resume.txt", "text": "Built Python systems for a team."},
            ).status_code
            == 201
        )
        state = client.get("/v1/profile/state", headers=headers).json()
        state["profile"]["name"] = "Casey"
        saved = client.patch(
            "/v1/profile",
            headers=headers,
            json={"expected_version": state["version"], "profile": state["profile"]},
        ).json()
        assert (
            client.post(
                f"/v1/profile/confirm?expected_version={saved['version']}", headers=headers
            ).status_code
            == 200
        )
        job = {
            "@type": "JobPosting",
            "title": "Engineer",
            "hiringOrganization": {"name": "Example Co"},
            "description": "Build Python systems.",
            "validThrough": "2020-01-01",
        }
        html = '<script type="application/ld+json">' + json.dumps(job) + "</script>"
        with patch("operator_api.extraction.fetch", return_value=("https://jobs.example/expired", html)):
            imported = client.post(
                "/v1/opportunities/import",
                headers=headers,
                json={"url": "https://jobs.example/expired"},
            ).json()
        assert imported["posting"]["valid_through"] == "2020-01-01"
        assert (
            client.patch(
                f"/v1/opportunities/imports/{imported['import_id']}/review",
                headers=headers,
                json={"expected_version": 1, "requirements": []},
            ).status_code
            == 200
        )
        mission = client.post(
            "/v1/missions",
            headers=headers,
            json={"job_url": "https://jobs.example/expired"},
        ).json()
        blocked = client.post(f"/v1/missions/{mission['id']}/start", headers=headers)
        assert blocked.status_code == 409
        assert "expired" in blocked.json()["detail"]
