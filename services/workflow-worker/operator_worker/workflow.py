from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn
class OpportunityMissionWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        outputs = {}
        for step in ("planning", "extracting", "matching", "verifying", "generating"):
            activity_input = {**request, "step": step, "inputs": outputs}
            try:
                output = await workflow.execute_activity(
                    "execute_step",
                    activity_input,
                    start_to_close_timeout=timedelta(seconds=30),
                    schedule_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=5),
                        maximum_attempts=3,
                    ),
                )
            except ActivityError:
                # Persist failure before closing. Retry recording until storage recovers.
                await workflow.execute_activity(
                    "mark_failed", {**request, "step": step}, start_to_close_timeout=timedelta(seconds=15)
                )
                return {"status": "failed", "step": step}
            if output.get("stopped"):
                return {"status": "cancelled"}
            outputs[step] = output
        return {"status": "completed", "result": outputs["generating"]}
