"""Live Temporal tests. Enable with OPERATOR_RUN_TEMPORAL_TESTS=1."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from operator_api.db import (
    Artifact,
    Approval,
    Application,
    DispatchCommand,
    Event,
    Mission,
    MissionRun,
    MissionStep,
    database,
)
import operator_api.main as api_main
from operator_api.main import create_app
from operator_worker.activities import Activities
from operator_worker.dispatcher import dispatch_once
from operator_worker.workflow import OpportunityMissionWorkflow


@pytest.mark.skipif(
    os.getenv("OPERATOR_RUN_TEMPORAL_TESTS") != "1",
    reason="Enable live Temporal integration tests explicitly",
)
def test_real_temporal_execution_recovery_and_replay(tmp_path):
    asyncio.run(run_scenarios(tmp_path))


async def run_scenarios(tmp_path):
    environment = None
    address = os.getenv("TEMPORAL_ADDRESS")
    if address:
        temporal = await Client.connect(address)
    else:
        download = Path(__file__).resolve().parents[2] / ".local/temporal"
        download.mkdir(parents=True, exist_ok=True)
        environment = await WorkflowEnvironment.start_local(download_dest_dir=str(download))
        temporal = environment.client
    url = f"sqlite:///{tmp_path / 'temporal.db'}"
    engine, sessions = database(url)
    activities = Activities(sessions)
    task_queue = f"operator-test-{uuid4()}"
    previous_temporal_client = api_main._TEMPORAL_CLIENT
    api_main._TEMPORAL_CLIENT = temporal
    try:
        with TestClient(create_app(url)) as api, ThreadPoolExecutor(max_workers=4) as executor:
            token = api.post("/v1/guest-sessions?demo=true").json()["token"]
            headers = {"Authorization": f"Bearer {token}"}

            def create(mode=None):
                mid = api.post(
                    "/v1/missions",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json={"job_url": "https://example.com/jobs/1"},
                ).json()["id"]
                if mode:
                    api.post(f"/v1/missions/{mid}/simulate-failure", headers=headers, json={"mode": mode})
                assert api.post(f"/v1/missions/{mid}/start", headers=headers).status_code == 202
                return mid

            def worker():
                return Worker(
                    temporal,
                    task_queue=task_queue,
                    workflows=[OpportunityMissionWorkflow],
                    activities=[
                        activities.execute_step,
                        activities.mark_failed,
                        activities.request_approval,
                        activities.resolve_approval_wait,
                    ],
                    activity_executor=executor,
                )

            async def result(mid, number=1):
                workflow_id = f"opportunity-{mid}-{number}"
                while True:
                    with sessions() as db:
                        approval = db.scalar(
                            select(Approval).where(
                                Approval.mission_id == mid,
                                Approval.status == "pending",
                            )
                        )
                    if approval:
                        response = api.post(
                            f"/v1/approvals/{approval.id}/approve",
                            headers=headers,
                            json={"note": "live Temporal integration test"},
                        )
                        assert response.status_code == 200
                        assert response.json()["status"] == "approved"
                        break
                    handle = temporal.get_workflow_handle(workflow_id)
                    description = await handle.describe()
                    if description.status.name != "RUNNING":
                        break
                    await asyncio.sleep(0.02)
                return await asyncio.wait_for(
                    temporal.get_workflow_handle(workflow_id).result(), 60
                )

            # Deliver while no worker is alive: Temporal must retain the work.
            mid = create("transient")
            await dispatch_once(temporal, sessions, task_queue)
            async with worker():
                # Stop the worker during the retry backoff, with this workflow still open.
                async def matching_failed():
                    while True:
                        with sessions() as db:
                            if db.scalar(
                                select(Event).where(Event.mission_id == mid, Event.type == "step.failed")
                            ):
                                return
                        await asyncio.sleep(0.02)

                await asyncio.wait_for(matching_failed(), 30)
            async with worker():
                assert (await result(mid))["status"] == "completed"
                with sessions() as db:
                    assert db.get(MissionRun, mid).result["score"] == 100
                    assert len(db.get(MissionRun, mid).result["artifact_ids"]) == 4
                    drafts = db.scalars(select(Artifact).where(Artifact.mission_id == mid)).all()
                    assert len(drafts) == 4 and all(draft.status == "draft" for draft in drafts)
                    assert (
                        db.scalar(select(Application).where(Application.mission_id == mid)).company
                        == "Northstar"
                    )
                    steps = db.scalars(select(MissionStep).where(MissionStep.mission_id == mid)).all()
                    assert next(s for s in steps if s.name == "matching").attempt == 2
                # Simulate crash after Temporal accepted a start but before the outbox acknowledgement.
                with sessions.begin() as db:
                    db.scalar(
                        select(DispatchCommand).where(DispatchCommand.mission_id == mid)
                    ).dispatched_at = None
                await dispatch_once(temporal, sessions, task_queue)
                with sessions() as db:
                    assert (
                        len(
                            db.scalars(
                                select(Event).where(
                                    Event.mission_id == mid, Event.type == "mission.completed"
                                )
                            ).all()
                        )
                        == 1
                    )
                failed = create("exhausted")
                await dispatch_once(temporal, sessions, task_queue)
                assert (await result(failed))["status"] == "failed"
            # A new worker resumes the retry from persisted completed checkpoints.
            assert api.post(f"/v1/missions/{failed}/retry", headers=headers).status_code == 202
            await dispatch_once(temporal, sessions, task_queue)
            async with worker():
                assert (await result(failed, 2))["status"] == "completed"
                with sessions() as db:
                    planning = db.scalar(
                        select(MissionStep).where(
                            MissionStep.mission_id == failed, MissionStep.name == "planning"
                        )
                    )
                    assert planning.attempt == 1
                    events = db.scalars(
                        select(Event).where(Event.mission_id == failed).order_by(Event.sequence)
                    ).all()
                    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
            cancelled = create()
            api.post(f"/v1/missions/{cancelled}/cancel", headers=headers)
            await dispatch_once(temporal, sessions, task_queue)
            with sessions() as db:
                assert db.get(Mission, cancelled).status == "cancelled"
                assert db.get(MissionRun, cancelled).result is None
    finally:
        api_main._TEMPORAL_CLIENT = previous_temporal_client
        engine.dispose()
        if environment:
            await environment.shutdown()
