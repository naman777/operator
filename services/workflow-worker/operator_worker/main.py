import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker
from operator_api.db import database
from .activities import Activities
from .dispatcher import TASK_QUEUE, dispatch_forever
from .workflow import OpportunityMissionWorkflow


async def main():
    logging.basicConfig(level=logging.INFO)
    engine, sessions = database()
    client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    activities = Activities(sessions)
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            async with Worker(
                client,
                task_queue=TASK_QUEUE,
                workflows=[OpportunityMissionWorkflow],
                activities=[
                    activities.execute_step,
                    activities.mark_failed,
                    activities.request_approval,
                    activities.resolve_approval_wait,
                ],
                activity_executor=executor,
            ):
                await dispatch_forever(client, sessions)
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
