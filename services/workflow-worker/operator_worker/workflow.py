"""Durable Opportunity Mission workflow with awaiting_approval stage.

The workflow pauses at awaiting_approval and waits for an approval signal
from the API (approve or reject). Without a signal within 24 hours the run
is automatically cancelled. This keeps the Temporal history event-sourced
while the human decision is recorded transactionally in PostgreSQL.
"""

from datetime import timedelta
from typing import Optional
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError


APPROVAL_SIGNAL = "approval_resolved"


@workflow.defn
class OpportunityMissionWorkflow:
    def __init__(self):
        self._approved: Optional[bool] = None

    @workflow.signal(name=APPROVAL_SIGNAL)
    def approval_resolved(self, approved: bool) -> None:
        """Receive the human approve/reject decision from the API."""
        self._approved = approved

    @workflow.run
    async def run(self, request: dict) -> dict:
        outputs = {}
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=5),
            maximum_attempts=3,
        )

        for step in ("planning", "extracting", "researching", "matching", "verifying"):
            activity_input = {**request, "step": step, "inputs": outputs}
            try:
                output = await workflow.execute_activity(
                    "execute_step",
                    activity_input,
                    start_to_close_timeout=timedelta(seconds=30),
                    schedule_to_close_timeout=timedelta(minutes=3),
                    retry_policy=retry,
                )
            except (ActivityError, CancelledError):
                await workflow.execute_activity(
                    "mark_failed",
                    {**request, "step": step},
                    start_to_close_timeout=timedelta(seconds=15),
                )
                return {"status": "failed", "step": step}
            if output.get("stopped"):
                return {"status": "cancelled"}
            outputs[step] = output

        # ── Awaiting approval ────────────────────────────────────────────────
        # Record the approval request durably; signal will set self._approved.
        try:
            await workflow.execute_activity(
                "request_approval",
                {**request, "step": "awaiting_approval", "inputs": outputs},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
        except (ActivityError, CancelledError):
            await workflow.execute_activity(
                "mark_failed",
                {**request, "step": "awaiting_approval"},
                start_to_close_timeout=timedelta(seconds=15),
            )
            return {"status": "failed", "step": "awaiting_approval"}

        try:
            await workflow.wait_condition(
                lambda: self._approved is not None,
                timeout=timedelta(hours=24),
            )
        except TimeoutError:
            await workflow.execute_activity(
                "resolve_approval_wait",
                {**request, "outcome": "timeout"},
                start_to_close_timeout=timedelta(seconds=15),
            )
            return {"status": "cancelled", "reason": "approval_timeout"}

        if not self._approved:
            await workflow.execute_activity(
                "resolve_approval_wait",
                {**request, "outcome": "rejected"},
                start_to_close_timeout=timedelta(seconds=15),
            )
            return {"status": "cancelled", "reason": "rejected"}

        await workflow.execute_activity(
            "resolve_approval_wait",
            {**request, "outcome": "approved"},
            start_to_close_timeout=timedelta(seconds=15),
        )

        # ── Generating ───────────────────────────────────────────────────────
        activity_input = {**request, "step": "generating", "inputs": outputs}
        try:
            output = await workflow.execute_activity(
                "execute_step",
                activity_input,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(minutes=3),
                retry_policy=retry,
            )
        except (ActivityError, CancelledError):
            await workflow.execute_activity(
                "mark_failed",
                {**request, "step": "generating"},
                start_to_close_timeout=timedelta(seconds=15),
            )
            return {"status": "failed", "step": "generating"}
        if output.get("stopped"):
            return {"status": "cancelled"}
        return {"status": "completed", "result": output}
