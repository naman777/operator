from uuid import uuid4

from fastapi.testclient import TestClient

from operator_api.main import create_app


def setup(client):
    token = client.post("/v1/guest-sessions?demo=true").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    mission = client.post(
        "/v1/missions",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"job_url": "https://example.com/jobs/1"},
    ).json()
    return headers, mission


def test_email_draft_requires_editable_approval_and_is_idempotent(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'email.db'}")) as client:
        headers, mission = setup(client)
        proposed = client.post(
            "/v1/actions/propose",
            headers=headers,
            json={
                "mission_id": mission["id"],
                "action_type": "email_draft",
                "proposed_payload": {
                    "to": "recruiter@example.com",
                    "subject": "Application follow-up",
                    "body": "Original draft",
                },
            },
        )
        assert proposed.status_code == 201
        approval = proposed.json()
        assert approval["status"] == "pending"
        assert approval["risk_level"] == "low"
        edited = client.patch(
            f"/v1/approvals/{approval['id']}/proposal",
            headers=headers,
            json={
                "proposed_payload": {
                    "to": "recruiter@example.com",
                    "subject": "Application follow-up",
                    "body": "Reviewed draft",
                }
            },
        )
        assert edited.status_code == 200
        assert edited.json()["proposed_payload"]["body"] == "Reviewed draft"
        assert client.get("/v1/actions", headers=headers).json() == []

        approved = client.post(
            f"/v1/approvals/{approval['id']}/approve", headers=headers, json={}
        )
        assert approved.status_code == 200
        actions = client.get("/v1/actions", headers=headers).json()
        assert len(actions) == 1
        assert actions[0]["provider"] == "mock"
        assert actions[0]["payload"]["body"] == "Reviewed draft"
        assert client.post(
            f"/v1/approvals/{approval['id']}/approve", headers=headers, json={}
        ).status_code == 200
        assert len(client.get("/v1/actions", headers=headers).json()) == 1


def test_calendar_validation_rejection_and_workspace_isolation(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'calendar.db'}")) as client:
        headers, mission = setup(client)
        invalid = client.post(
            "/v1/actions/propose",
            headers=headers,
            json={
                "mission_id": mission["id"],
                "action_type": "calendar_event",
                "proposed_payload": {
                    "title": "Interview",
                    "starts_at": "2027-06-01T11:00:00Z",
                    "ends_at": "2027-06-01T10:00:00Z",
                },
            },
        )
        assert invalid.status_code == 422
        proposed = client.post(
            "/v1/actions/propose",
            headers=headers,
            json={
                "mission_id": mission["id"],
                "action_type": "calendar_event",
                "proposed_payload": {
                    "title": "Interview",
                    "starts_at": "2027-06-01T10:00:00Z",
                    "ends_at": "2027-06-01T11:00:00Z",
                    "attendee": "interviewer@example.com",
                },
            },
        ).json()
        assert proposed["risk_level"] == "medium"
        assert client.post(
            f"/v1/approvals/{proposed['id']}/reject", headers=headers, json={}
        ).status_code == 200
        assert client.get("/v1/actions", headers=headers).json() == []

        other = client.post("/v1/guest-sessions?demo=true").json()["token"]
        other_headers = {"Authorization": f"Bearer {other}"}
        assert client.get("/v1/actions", headers=other_headers).json() == []
        assert client.patch(
            f"/v1/approvals/{proposed['id']}/proposal",
            headers=other_headers,
            json={"proposed_payload": {}},
        ).status_code == 404
