import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import select
from temporalio.exceptions import WorkflowAlreadyStartedError
from operator_api.db import DispatchCommand, Event, Mission, database, utcnow
from operator_api.main import create_app
from operator_worker.dispatcher import dispatch_once


def test_outage_and_duplicate_delivery_are_recoverable(tmp_path):
    url = f"sqlite:///{tmp_path / 'dispatch.db'}"
    engine, sessions = database(url)
    with TestClient(create_app(url)) as api:
        token = api.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "dispatch-mission"}
        mid = api.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()["id"]
        api.post(f"/v1/missions/{mid}/start", headers=headers)
        temporal = AsyncMock()
        temporal.start_workflow.side_effect = ConnectionError("unavailable")
        asyncio.run(dispatch_once(temporal, sessions))
        with sessions.begin() as db:
            row = db.scalar(select(DispatchCommand))
            assert row.dispatched_at is None
            assert row.attempts == 1
            assert row.last_error == "ConnectionError"
            row.next_attempt_at = utcnow() - timedelta(seconds=1)
        temporal.start_workflow.side_effect = WorkflowAlreadyStartedError(
            "existing", "OpportunityMissionWorkflow"
        )
        asyncio.run(dispatch_once(temporal, sessions))
        with sessions() as db:
            assert db.scalar(select(DispatchCommand)).dispatched_at is not None
    engine.dispose()


def test_exhausted_dispatch_is_dead_lettered_once(tmp_path):
    url = f"sqlite:///{tmp_path / 'dead-letter.db'}"
    engine, sessions = database(url)
    with TestClient(create_app(url)) as api:
        token = api.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "dead-letter-mission"}
        mid = api.post(
            "/v1/missions", headers=headers, json={"job_url": "https://example.com/jobs/1"}
        ).json()["id"]
        api.post(f"/v1/missions/{mid}/start", headers=headers)
        temporal = AsyncMock()
        temporal.start_workflow.side_effect = ConnectionError("private provider detail")
        asyncio.run(dispatch_once(temporal, sessions, max_attempts=1))
        asyncio.run(dispatch_once(temporal, sessions, max_attempts=1))
        with sessions() as db:
            row = db.scalar(select(DispatchCommand))
            assert row.dead_lettered_at is not None
            assert row.attempts == 1
            assert row.last_error == "ConnectionError"
            assert db.get(Mission, mid).status == "failed"
            events = db.scalars(
                select(Event).where(Event.mission_id == mid, Event.type == "mission.dispatch_dead_lettered")
            ).all()
            assert len(events) == 1
            assert events[0].payload["retryable"] is False
            assert "private provider detail" not in str(events[0].payload)
    engine.dispose()
