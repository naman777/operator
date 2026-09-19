"""Temporal activities: each activity is idempotent and records step events."""

import time
from datetime import timedelta
from uuid import uuid4
from temporalio import activity
from temporalio.exceptions import ApplicationError
from operator_api import runtime, profiles, research
from operator_api.schemas import JobPosting, CandidateProfile
from operator_api.db import Approval, Mission, ModelCall, utcnow
from sqlalchemy import func, select
from .analysis import match, result, verify
from .model_runtime import capture_usage, enabled as model_enabled
from .model_runtime import enrich_job, enrich_matches, generate_drafts


def job_from_step(payload):
    clean = dict(payload)
    clean.pop("_model_calls", None)
    clean.pop("_model_fallback", None)
    return JobPosting.model_validate(clean)


class Activities:
    def __init__(self, sessions):
        self.sessions = sessions

    def remaining_budget(self, mission_id):
        with self.sessions() as db:
            mission = db.get(Mission, mission_id)
            spent = db.scalar(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(ModelCall.mission_id == mission_id))
            return max(0.0, mission.budget_usd - float(spent or 0))

    def record_usage(self, mission_id, step, records):
        if not records:
            return
        with self.sessions.begin() as db:
            for record in records:
                db.add(ModelCall(id=str(uuid4()), mission_id=mission_id, step=step, **record))

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
                budget_usd = self.remaining_budget(mission_id)
                with capture_usage() as usage:
                    posting, model_calls, fallback = enrich_job(
                        JobPosting.model_validate(inputs["planning"]["job_posting"]), budget_usd
                    )
                self.record_usage(mission_id, name, usage)
                payload = posting.model_dump(mode="json")
                payload.update({"_model_calls": model_calls, "_model_fallback": fallback})
            elif name == "researching":
                payload = research.company(job_from_step(inputs["extracting"])).model_dump(mode="json")
            elif name == "matching":
                job = job_from_step(inputs["extracting"])
                profile = CandidateProfile.model_validate(inputs["planning"]["candidate_profile"])
                with self.sessions() as db:
                    mission = db.get(Mission, mission_id)
                    profile = profiles.retrieve(db, mission.workspace_id, profile, job.requirements)
                budget_usd = self.remaining_budget(mission_id)
                with capture_usage() as usage:
                    payload = enrich_matches(job, profile, match(job, profile), budget_usd)
                self.record_usage(mission_id, name, usage)
                payload["model_calls"] = payload.get("model_calls", 0) + inputs["extracting"].get(
                    "_model_calls", 0
                )
            elif name == "verifying":
                payload = verify(job_from_step(inputs["extracting"]), inputs["matching"])
            elif name == "generating":
                payload = result(
                    mission_id,
                    inputs["matching"],
                    inputs["verifying"],
                    inputs.get("researching"),
                )
                job = job_from_step(inputs["extracting"])
                profile = CandidateProfile.model_validate(inputs["planning"]["candidate_profile"])
                budget_usd = self.remaining_budget(mission_id)
                with capture_usage() as usage:
                    drafts = generate_drafts(job, profile, inputs["matching"], budget_usd)
                self.record_usage(mission_id, name, usage)
                payload["_model_calls"] = inputs["matching"].get("model_calls", 0) + int(
                    model_enabled(budget_usd)
                )
                if drafts:
                    payload["_model_drafts"] = drafts
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
