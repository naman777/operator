from fastapi.testclient import TestClient

from operator_api.db import ImportedJob, database
from operator_api.main import create_app


def test_workspace_export_is_scoped_and_excludes_credentials(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'export.db'}"
    with TestClient(create_app(db_url)) as client:
        first = client.post("/v1/guest-sessions").json()
        second = client.post("/v1/guest-sessions").json()
        first_headers = {"Authorization": f"Bearer {first['token']}"}
        second_headers = {"Authorization": f"Bearer {second['token']}"}
        assert client.get("/v1/workspace/export").status_code == 401

        own = client.post(
            "/v1/profile/documents", headers=first_headers,
            json={"name": "own-resume.txt", "text": "Private candidate evidence"},
        )
        assert own.status_code == 201
        other = client.post(
            "/v1/profile/documents", headers=second_headers,
            json={"name": "other-resume.txt", "text": "Other workspace secret"},
        )
        assert other.status_code == 201

        engine, sessions = database(db_url)
        with sessions() as db:
            db.add(ImportedJob(
                id="own-job", workspace_id=first["workspace"]["id"],
                original_url="https://example.com/job", content_hash="hash",
                posting={"title": "Engineer"}, snapshot="public job source",
                screenshot=b"image bytes", version=1,
            ))
            db.commit()
        engine.dispose()

        response = client.get("/v1/workspace/export", headers=first_headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert "attachment" in response.headers["content-disposition"]
        exported = response.json()
        assert exported["format_version"] == 1
        assert exported["workspace"]["id"] == first["workspace"]["id"]
        assert exported["documents"][0]["text"] == "Private candidate evidence"
        assert exported["imported_jobs"][0]["snapshot"] == "public job source"
        assert exported["imported_jobs"][0]["screenshot_base64"] == "aW1hZ2UgYnl0ZXM="
        assert "Other workspace secret" not in response.text
        assert first["token"] not in response.text
        assert second["token"] not in response.text
        assert "token_hash" not in response.text
        assert "password_hash" not in response.text
        assert client.get("/v1/workspace/export", headers=second_headers).json()["imported_jobs"] == []
