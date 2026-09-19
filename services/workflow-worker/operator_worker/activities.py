"""Temporal activities: each activity is idempotent and records step events."""

import time
from datetime import timedelta
from uuid import uuid4
from temporalio import activity
from temporalio.exceptions import ApplicationError
from operator_api import runtime, profiles
from operator_api.schemas import JobPosting, CandidateProfile
from operator_api.db import Approval, Mission, utcnow
from .analysis import match, result, verify


class Activities:
    def __init__(self, sessions):
        self.sessions = sessions

    @activity.defn
    def execute_step(self, request: dict) -> dict:
        mission_id, run_number, name = request["mission_id"], request["run_number"], request["step"]
        start = time.perf_counter()
        state = runtime.begin_step(self.sessions, mission_id, run_number, name)
        if state.get("stopped"):
            return state
        if "cached" in state:
            return state["cached"]
        if state.get("simulate_failure"):
            raise ApplicationError("Simulated temporary matching failure", type="SimulatedFailure")
        inputs = request.get("inputs", {})
        try:
            if name == "planning":
                with self.sessions() as db:
                    mission = db.get(Mission, mission_id)
                    profile = profiles.load(db, mission.workspace_id, runtime.sample_profile)
                    job = runtime.load_job(db, mission)
                payload = {
                    "candidate_profile": profile.model_dump(mode="json"),
                    "job_posting": job.model_dump(mode="json"),
                    "steps": list(runtime.STEP_NAMES),
                    "execution_mode": "synthetic-fixture",
                    "job_url": state["job_url"],
                    "model_calls": 0,
                }
            elif name == "extracting":
                payload = inputs["planning"]["job_posting"]
            elif name == "matching":
                payload = match(
                    JobPosting.model_validate(inputs["extracting"]),
                    CandidateProfile.model_validate(inputs["planning"]["candidate_profile"]),
                )
            elif name == "verifying":
                payload = verify(JobPosting.model_validate(inputs["extracting"]), inputs["matching"])
            elif name == "generating":
                payload = result(mission_id, inputs["matching"], inputs["verifying"])
            else:
                raise ValueError("Unregistered fixture activity")
        except ValueError as exc:
            raise ApplicationError(str(exc), type="InvalidFixture", non_retryable=True) from exc
        return runtime.finish_step(
            self.sessions, mission_id, run_number, name, payload, round((time.perf_counter() - start) * 1000)
        )

    @activity.defn
    def request_approval(self, request: dict) -> dict:
        """Create a pending Approval record and record the awaiting_approval event.

        Idempotent: if an approval already exists for this mission run it returns
        the existing record without creating a duplicate.
        """
        mission_id = request["mission_id"]
        run_number = request["run_number"]
        workflow_id = f"opportunity-{mission_id}-{run_number}"

        with self.sessions.begin() as db:
            mission = db.get(Mission, mission_id)
            if not mission or mission.status in {"cancelled", "failed", "completed"}:
                return {"stopped": True}

            # Check for existing approval (idempotent on re-schedule).
            from sqlalchemy import select
            existing = db.scalar(
                select(Approval).where(
                    Approval.mission_id == mission_id,
                    Approval.status == "pending",
                )
            )
            if existing:
                existing.workflow_id = workflow_id
                return {"approval_id": existing.id, "workflow_id": workflow_id}

            approval = Approval(
                id=str(uuid4()),
                mission_id=mission_id,
                workspace_id=mission.workspace_id,
                action_type="pipeline_update",
                proposed_payload={
                    "action": "create_application",
                    "description": "Submit the generated application pack and create an application entry in the pipeline.",
                },
                expires_at=utcnow() + timedelta(hours=24),
                workflow_id=workflow_id,
            )
            db.add(approval)
            mission.status = "awaiting_approval"
            runtime.record_event(
                db,
                mission,
                "approval.requested",
                {
                    "approval_id": approval.id,
                    "action_type": approval.action_type,
                    "expires_in_hours": 24,
                },
            )
        return {"approval_id": approval.id, "workflow_id": workflow_id}

    @activity.defn
    def resolve_approval_wait(self, request: dict) -> dict:
        """Persist the workflow state reached after an approval decision or timeout."""
        mission_id = request["mission_id"]
        outcome = request["outcome"]
        with self.sessions.begin() as db:
            mission = db.get(Mission, mission_id)
            if not mission or mission.status in {"cancelled", "failed", "completed"}:
                return {"stopped": True}
            if outcome == "approved":
                mission.status = "running"
                runtime.record_event(db, mission, "approval.resolved", {"status": "approved"})
            else:
                mission.status = "cancelled"
                runtime.record_event(
                    db,
                    mission,
                    "mission.cancelled",
                    {"reason": "approval_timeout" if outcome == "timeout" else "approval_rejected"},
                )
        return {"status": outcome}

    @activity.defn
    def mark_failed(self, request: dict) -> None:
        runtime.fail_mission(self.sessions, request["mission_id"], request["run_number"], request["step"])
