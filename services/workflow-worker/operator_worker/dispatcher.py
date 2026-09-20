"""At-least-once delivery; stable Temporal IDs close the start/ack crash window."""

import asyncio
from datetime import timedelta
import logging
import os
from sqlalchemy import select
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode
from operator_api.db import DispatchCommand, Mission, utcnow
from operator_api.runtime import lock_mission, record_event

logger = logging.getLogger(__name__)
TASK_QUEUE = "operator-opportunities"


async def dispatch_once(client, sessions, task_queue=TASK_QUEUE, max_attempts=None):
    if max_attempts is None:
        max_attempts = int(os.getenv("OPERATOR_DISPATCH_MAX_ATTEMPTS", "8"))
    if max_attempts < 1:
        raise ValueError("OPERATOR_DISPATCH_MAX_ATTEMPTS must be positive")
    with sessions() as db:
        commands = db.scalars(
            select(DispatchCommand)
            .where(
                DispatchCommand.dispatched_at.is_(None),
                DispatchCommand.dead_lettered_at.is_(None),
                DispatchCommand.next_attempt_at <= utcnow(),
            )
            .order_by(DispatchCommand.created_at)
            .limit(25)
        ).all()
    for command in commands:
        try:
            with sessions() as db:
                mission = db.get(Mission, command.mission_id)
                cancelled = mission.status == "cancelled"
            if command.command == "start" and not cancelled:
                try:
                    await client.start_workflow(
                        "OpportunityMissionWorkflow",
                        {"mission_id": command.mission_id, "run_number": command.run_number},
                        id=command.workflow_id,
                        task_queue=task_queue,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        rpc_timeout=timedelta(seconds=5),
                    )
                except WorkflowAlreadyStartedError:
                    pass
            elif command.command == "cancel":
                try:
                    await client.get_workflow_handle(command.workflow_id).cancel(
                        rpc_timeout=timedelta(seconds=5)
                    )
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        raise
            with sessions.begin() as db:
                row = db.get(DispatchCommand, command.id)
                row.dispatched_at = utcnow()
                row.last_error = None
        except Exception as exc:
            # Keep the error category, not provider messages that could contain private input.
            with sessions.begin() as db:
                row = db.get(DispatchCommand, command.id)
                if row.dispatched_at is None:
                    row.attempts += 1
                    row.last_error = type(exc).__name__
                    if row.attempts >= max_attempts:
                        row.dead_lettered_at = utcnow()
                        mission = lock_mission(db, row.mission_id)
                        if row.command == "start" and mission.status not in {
                            "completed",
                            "cancelled",
                            "failed",
                        }:
                            mission.status = "failed"
                        record_event(
                            db,
                            mission,
                            "mission.dispatch_dead_lettered",
                            {
                                "command": row.command,
                                "attempts": row.attempts,
                                "error": row.last_error,
                                "retryable": False,
                            },
                        )
                    else:
                        row.next_attempt_at = utcnow() + timedelta(
                            seconds=min(60, 2 ** min(row.attempts, 6))
                        )
            logger.warning(
                "Dispatch %s after %s: %s",
                "dead-lettered" if command.attempts + 1 >= max_attempts else "deferred",
                command.attempts + 1,
                type(exc).__name__,
            )


async def dispatch_forever(client, sessions):
    while True:
        await dispatch_once(client, sessions)
        await asyncio.sleep(1)
