from fastapi.testclient import TestClient

from operator_api.main import create_app


def test_field_sources_are_independent_and_server_controlled(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'field-sources.db'}")) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={
                "name": "resume.txt",
                "text": "Education\nGraduated 2022\nExperience\nEngineer 2020 - 2022\nBuilt Python services.",
            },
        )
        assert first.status_code == 201
        state = client.get("/v1/profile/state", headers=headers).json()
        assert state["profile"]["field_sources"]["graduation_year"] == "heuristic-v1"
        assert state["profile"]["field_sources"]["experience_years"] == "heuristic-v1"
        assert state["profile"]["field_sources"]["skills"] == "heuristic-v1"
        for field in ("graduation_year", "experience_years", "skills"):
            refs = state["profile"]["field_evidence_ids"][field]
            assert refs
            assert set(refs) <= {item["id"] for item in state["profile"]["evidence"]}

        tampered = {**state["profile"], "field_sources": {"graduation_year": "user-correction"}}
        assert (
            client.patch(
                "/v1/profile",
                headers=headers,
                json={"expected_version": state["version"], "profile": tampered},
            ).status_code
            == 422
        )
        tampered = {**state["profile"], "field_evidence_ids": {"graduation_year": ["fake"]}}
        assert (
            client.patch(
                "/v1/profile",
                headers=headers,
                json={"expected_version": state["version"], "profile": tampered},
            ).status_code
            == 422
        )

        corrected = dict(state["profile"])
        corrected.update(
            name="Casey",
            experience_years=4.5,
            skills=["CustomSkill"],
            available_from="2026-10-01",
            employment_type_preference=["full-time"],
        )
        saved = client.patch(
            "/v1/profile",
            headers=headers,
            json={"expected_version": state["version"], "profile": corrected},
        )
        assert saved.status_code == 200
        sources = saved.json()["profile"]["field_sources"]
        assert sources["experience_years"] == "user-correction"
        assert sources["graduation_year"] == "heuristic-v1"
        assert sources["available_from"] == "user-correction"
        assert sources["employment_type_preference"] == "user-correction"
        assert saved.json()["profile"]["field_evidence_ids"].get("experience_years") is None
        assert saved.json()["profile"]["field_evidence_ids"].get("skills") is None
        confirmed = client.post(
            f"/v1/profile/confirm?expected_version={saved.json()['version']}", headers=headers
        )
        assert confirmed.status_code == 200
        unchanged = client.patch(
            "/v1/profile",
            headers=headers,
            json={"expected_version": saved.json()["version"], "profile": saved.json()["profile"]},
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["version"] == saved.json()["version"]
        assert unchanged.json()["reviewed_version"] == saved.json()["version"]

        second = client.post(
            "/v1/profile/documents",
            headers=headers,
            json={
                "name": "update.txt",
                "text": "Education\nGraduated 2024\nExperience\nEngineer 2018 - 2024\nBuilt Docker systems.",
            },
        )
        assert second.status_code == 201
        profile = client.get("/v1/profile", headers=headers).json()
        assert profile["graduation_year"] == 2024
        assert profile["experience_years"] == 4.5
        assert profile["skills"] == ["CustomSkill"]
        assert profile["field_sources"]["graduation_year"] == "heuristic-v1"
        assert profile["field_sources"]["experience_years"] == "user-correction"
        assert profile["field_sources"]["skills"] == "user-correction"
        assert all(
            "2024" in item["text"]
            for item in profile["evidence"]
            if item["id"] in profile["field_evidence_ids"]["graduation_year"]
        )


def test_deleting_inferred_evidence_clears_unsupported_fields(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'remove-source.db'}")) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            client.post(
                "/v1/profile/documents",
                headers=headers,
                json={
                    "name": "resume.txt",
                    "text": "Education\nGraduated 2022\nExperience\nEngineer 2020 - 2022\nBuilt Python services.",
                },
            ).status_code
            == 201
        )
        state = client.get("/v1/profile/state", headers=headers).json()
        for field in ("graduation_year", "experience_years", "skills"):
            evidence_id = state["profile"]["field_evidence_ids"][field][0]
            deleted = client.delete(
                f"/v1/evidence/{evidence_id}",
                headers=headers,
                params={"expected_version": state["version"]},
            )
            assert deleted.status_code == 200
            state = client.get("/v1/profile/state", headers=headers).json()
            assert state["profile"][field] in (None, [])
            assert state["profile"]["field_evidence_ids"][field] == []
            assert state["profile"]["field_sources"][field] == "unprovided"
