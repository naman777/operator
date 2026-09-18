"""Exercise the running web proxy, API, Temporal worker, SSE, and draft artifacts."""

import json
import os
from uuid import uuid4
import httpx


def main():
    with httpx.Client(base_url=os.getenv("OPERATOR_WEB_URL", "http://127.0.0.1:3000"), timeout=45) as client:
        assert client.get("/").status_code == 200
        response = client.post("/api/v1/guest-sessions")
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["token"]}

        def post(path, body=None):
            response = client.post(
                "/api" + path, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
            )
            response.raise_for_status()
            return response.json()

        def stream(mid, after=0):
            events = []
            with client.stream(
                "GET", f"/api/v1/missions/{mid}/stream", headers={**headers, "Last-Event-ID": str(after)}
            ) as response:
                response.raise_for_status()
                assert response.headers["content-type"].startswith("text/event-stream")
                for line in response.iter_lines():
                    if line.startswith("data: ") and line != "data: {}":
                        events.append(json.loads(line[6:]))
            assert [event["sequence"] for event in events] == list(range(after + 1, after + len(events) + 1))
            return events

        mid = post("/v1/missions", {"job_url": "https://example.com/jobs/1"})["id"]
        post(f"/v1/missions/{mid}/simulate-failure", {"mode": "exhausted"})
        post(f"/v1/missions/{mid}/start")
        failed_events = stream(mid)
        assert failed_events[-1]["type"] == "mission.failed"
        post(f"/v1/missions/{mid}/retry")
        completed_events = stream(mid, failed_events[-1]["sequence"])
        assert completed_events[-1]["type"] == "mission.completed"
        response = client.get(f"/api/v1/missions/{mid}/run", headers=headers)
        response.raise_for_status()
        run = response.json()
        assert run["mission"]["status"] == "completed"
        assert run["result"]["score"] == 100
        assert run["result"]["eligibility"] == "unknown"
        assert run["run_number"] == 2
        assert next(s for s in run["steps"] if s["name"] == "planning")["attempt"] == 1
        assert next(s for s in run["steps"] if s["name"] == "matching")["attempt"] == 4
        response = client.get(f"/api/v1/missions/{mid}/artifacts", headers=headers)
        response.raise_for_status()
        drafts = response.json()
        assert len(drafts) == 4
        assert {d["id"] for d in drafts} == set(run["result"]["artifact_ids"])
        assert all(d["status"] == "draft" and d["content"]["citations"] for d in drafts)
        applications = client.get("/api/v1/applications", headers=headers).json()
        assert len(applications) == 1 and applications[0]["company"] == "Northstar"
        other = post("/v1/missions", {"job_url": "https://example.com/jobs/2"})["id"]
        # Cancel a saved draft to avoid racing an intentionally fast fixture workflow.
        post(f"/v1/missions/{other}/cancel")
        assert stream(other)[-1]["type"] == "mission.cancelled"
        print(
            "Full-stack smoke passed: proxy, guest session, dispatch, exhausted retries, checkpoint retry, SSE replay, four cited drafts, pipeline, cancellation."
        )


if __name__ == "__main__":
    main()
