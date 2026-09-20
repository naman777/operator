import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import operator_api.main as main_module
from operator_api.db import Approval, database
from operator_api.main import create_app


@pytest.mark.parametrize(
    ("decision", "expected_status", "signal_value", "repeat_status"),
    [
        ("approve", "approved", True, 200),
        ("reject", "rejected", False, 409),
    ],
)
def test_approval_endpoint_persists_before_signaling_temporal(
    tmp_path, monkeypatch, decision, expected_status, signal_value, repeat_status
):
    url = f"sqlite:///{tmp_path / f'{decision}.db'}"
    engine, sessions = database(url)
    calls = []

    class Handle:
        async def signal(self, name, value):
            asyncio.get_running_loop()
            with sessions() as session:
                persisted = session.get(Approval, approval_id)
                assert persisted.status == expected_status
                assert persisted.resolved_by == "user"
                assert persisted.resolved_at is not None
            calls.append((name, value))

    class TemporalClient:
        def get_workflow_handle(self, workflow_id):
            assert workflow_id == f"workflow-{decision}"
            return Handle()

    async def get_temporal_client():
        return TemporalClient()

    monkeypatch.setattr(main_module, "_get_temporal_client", get_temporal_client)

    with TestClient(create_app(url)) as client:
        guest = client.post("/v1/guest-sessions").json()
        headers = {"Authorization": f"Bearer {guest['token']}"}
        mission = client.post(
            "/v1/missions",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"job_url": "https://example.com/jobs/1"},
        ).json()
        approval_id = str(uuid4())
        with sessions.begin() as session:
            session.add(
                Approval(
                    id=approval_id,
                    mission_id=mission["id"],
                    workspace_id=mission["workspace_id"],
                    action_type="pipeline_update",
                    proposed_payload={"stage": "saved"},
                    workflow_id=f"workflow-{decision}",
                )
            )

        other_token = client.post("/v1/guest-sessions").json()["token"]
        isolated = client.post(
            f"/v1/approvals/{approval_id}/{decision}",
            headers={"Authorization": f"Bearer {other_token}"},
            json={},
        )
        assert isolated.status_code == 404
        assert calls == []

        response = client.post(
            f"/v1/approvals/{approval_id}/{decision}", headers=headers, json={}
        )
        assert response.status_code == 200
        assert response.json()["status"] == expected_status
        assert calls == [("approval_resolved", signal_value)]

        repeated = client.post(
            f"/v1/approvals/{approval_id}/{decision}", headers=headers, json={}
        )
        assert repeated.status_code == repeat_status
        assert calls == [("approval_resolved", signal_value)]

    engine.dispose()
