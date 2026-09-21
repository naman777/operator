import json
from fastapi.testclient import TestClient
from operator_api.main import create_app


def test_stream_replays_committed_events_and_last_event_id(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'stream.db'}")) as client:
        token = client.post("/v1/guest-sessions?demo=true").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "stream-test-0001"}
        mid = client.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()["id"]
        client.post(f"/v1/missions/{mid}/start", headers=headers)
        client.post(f"/v1/missions/{mid}/cancel", headers=headers)
        path = f"/v1/missions/{mid}/stream"
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: {}"
        ]
        assert [e["sequence"] for e in events] == [1, 2, 3]
        replay = client.get(path, headers={**headers, "Last-Event-ID": "2"})
        assert "id: 3\n" in replay.text
        assert "id: 2\n" not in replay.text
        assert "id:" not in client.get(path + "?after=3", headers=headers).text
        assert client.get(path, headers={**headers, "Last-Event-ID": "-1"}).status_code == 422
        assert client.get(path + "?after=-1", headers=headers).status_code == 422
        assert client.get(path).status_code == 401
        other = client.post("/v1/guest-sessions?demo=true").json()["token"]
        assert client.get(path, headers={"Authorization": f"Bearer {other}"}).status_code == 404
