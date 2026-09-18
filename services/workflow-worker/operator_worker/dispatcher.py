"""At-least-once delivery; stable Temporal IDs close the start/ack crash window."""

import asyncio
from datetime import timedelta
import logging
from sqlalchemy import select
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode
from operator_api.db import DispatchCommand, Mission, utcnow

logger = logging.getLogger(__name__)
TASK_QUEUE = "operator-opportunities"


async def dispatch_once(client, sessions, task_queue=TASK_QUEUE):
    with sessions() as db:
        commands = db.scalars(
            select(DispatchCommand)
            .where(DispatchCommand.dispatched_at.is_(None), DispatchCommand.next_attempt_at <= utcnow())
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
                    row.next_attempt_at = utcnow() + timedelta(seconds=min(60, 2 ** min(row.attempts, 6)))
            logger.warning("Dispatch deferred: %s", type(exc).__name__)


async def dispatch_forever(client, sessions):
    while True:
        await dispatch_once(client, sessions)
        await asyncio.sleep(1)
