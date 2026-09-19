"""Transactional workflow state. Lock the mission before allocating an event sequence."""

import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, update
from .db import (
    Application,
    Artifact,
    DispatchCommand,
    Event,
    Mission,
    MissionRun,
    MissionStep,
    Opportunity,
    StageHistory,
    StepOutput,
    Workspace,
    ImportedJob,
    ModelCall,
    utcnow,
)
from .schemas import CandidateProfile, JobPosting
from .artifacts import prepare as prepare_artifacts

STEP_NAMES = ("planning", "extracting", "matching", "verifying", "generating")
TERMINAL = {"completed", "failed", "cancelled"}
DATA = Path(os.getenv("OPERATOR_DATA_DIR", str(Path(__file__).resolve().parents[3] / "data/demo")))


class StateConflict(ValueError):
    pass


def sample_job(url):
    for path in sorted(DATA.glob("job-*.json")):
        job = JobPosting.model_validate_json(path.read_text(encoding="utf-8"))
        if str(job.url) == url:
            return job
    raise StateConflict("Execution currently supports only the three synthetic sample job URLs.")


def load_job(db, mission):
    imported = db.scalar(
        select(ImportedJob)
        .where(ImportedJob.workspace_id == mission.workspace_id, ImportedJob.original_url == mission.job_url)
        .order_by(ImportedJob.created_at.desc())
    )
    if imported:
        return JobPosting.model_validate(imported.posting)
    return sample_job(mission.job_url)


def sample_profile():
    return CandidateProfile.model_validate_json((DATA / "candidate.json").read_text(encoding="utf-8"))


def lock_mission(db, mission_id):
    db.execute(update(Mission).where(Mission.id == mission_id).values(status=Mission.status))
    mission = db.get(Mission, mission_id, populate_existing=True)
    if not mission:
        raise StateConflict("Mission not found")
    return mission


def record_event(db, mission, kind, payload):
    if "execution_mode" in payload:
        planning = db.scalar(
            select(MissionStep).where(MissionStep.mission_id == mission.id, MissionStep.name == "planning")
        )
        saved = db.get(StepOutput, planning.id) if planning else None
        posting = saved.output.get("job_posting", {}) if saved and saved.output else {}
        if posting and not posting.get("synthetic", True):
            payload = {**payload, "execution_mode": "public-snapshot"}
    sequence = (db.scalar(select(func.max(Event.sequence)).where(Event.mission_id == mission.id)) or 0) + 1
    event = Event(
        id=str(uuid4()),
        mission_id=mission.id,
        sequence=sequence,
        type=kind,
        payload={"status": mission.status, **payload},
    )
    db.add(event)
    db.flush()
    return event


def enqueue(db, mission, run, command):
    workflow_id = f"opportunity-{mission.id}-{run.run_number}"
    db.add(
        DispatchCommand(
            id=f"{workflow_id}-{command}",
            mission_id=mission.id,
            workflow_id=workflow_id,
            command=command,
            run_number=run.run_number,
        )
    )


def start_mission(db, mission_id, retry=False):
    mission = lock_mission(db, mission_id)
    if mission.status == "queued":
        return mission
    expected = "failed" if retry else "draft"
    if mission.status != expected:
        raise StateConflict(f"Only {expected} missions can be {'retried' if retry else 'started'}.")
    load_job(db, mission)
    run = db.get(MissionRun, mission_id)
    if run is None:
        run = MissionRun(mission_id=mission_id, run_number=1, failure_remaining=0)
        db.add(run)
    elif retry:
        run.run_number += 1
    if not retry:
        for name in STEP_NAMES:
            step = MissionStep(id=str(uuid4()), mission_id=mission_id, name=name)
            db.add(step)
            db.flush()
            db.add(StepOutput(step_id=step.id))
    else:
        # Completed steps retain their outputs. Only the failed activity resumes.
        for step in db.scalars(select(MissionStep).where(MissionStep.mission_id == mission_id)):
            if step.status != "completed":
                step.status = "pending"
    mission.status = "queued"
    db.flush()
    enqueue(db, mission, run, "start")
    record_event(
        db,
        mission,
        "mission.queued",
        {"run_number": run.run_number, "retry": retry, "execution_mode": "synthetic-fixture"},
    )
    return mission


def cancel_mission(db, mission_id):
    mission = lock_mission(db, mission_id)
    if mission.status == "cancelled":
        return mission
    if mission.status == "completed":
        raise StateConflict("Completed missions cannot be cancelled.")
    mission.status = "cancelled"
    run = db.get(MissionRun, mission_id)
    if run:
        enqueue(db, mission, run, "cancel")
    for step in db.scalars(select(MissionStep).where(MissionStep.mission_id == mission_id)):
        if step.status != "completed":
            step.status = "cancelled"
    record_event(db, mission, "mission.cancelled", {"message": "Cancelled by the user."})
    return mission


def simulate_failure(db, mission_id, mode):
    mission = lock_mission(db, mission_id)
    if mission.status != "draft":
        raise StateConflict("Configure failure simulation before starting a draft mission.")
    run = db.get(MissionRun, mission_id)
    if run is None:
        run = MissionRun(mission_id=mission_id, run_number=1)
        db.add(run)
    run.failure_remaining = 1 if mode == "transient" else 3
    record_event(db, mission, "failure.configured", {"step": "matching", "mode": mode})
    return mission


def run_view(db, mission):
    run = db.get(MissionRun, mission.id)
    steps = {
        step.name: step
        for step in db.scalars(select(MissionStep).where(MissionStep.mission_id == mission.id))
    }
    views = []
    for name in STEP_NAMES:
        if name not in steps:
            continue
        step = steps[name]
        output = db.get(StepOutput, step.id)
        views.append(
            {
                "id": step.id,
                "name": name,
                "status": step.status,
                "attempt": step.attempt,
                **{
                    key: getattr(output, key) if output else None
                    for key in ("output", "started_at", "completed_at", "latency_ms", "error")
                },
            }
        )
    return {
        "mission": mission,
        "run_number": run.run_number if run else 0,
        "steps": views,
        "result": run.result if run else None,
        "execution_mode": "public-snapshot"
        if any(
            view["name"] == "extracting" and view["output"] and not view["output"].get("synthetic", True)
            for view in views
        )
        else "synthetic-fixture",
    }


def begin_step(sessions, mission_id, run_number, name):
    with sessions.begin() as db:
        mission = lock_mission(db, mission_id)
        run = db.get(MissionRun, mission_id)
        if mission.status in {"cancelled", "failed"} or not run or run.run_number != run_number:
            return {"stopped": True}
        step = db.scalar(
            select(MissionStep).where(MissionStep.mission_id == mission_id, MissionStep.name == name)
        )
        output = db.get(StepOutput, step.id)
        if step.status == "completed":
            return {"cached": output.output}
        if mission.status == "completed":
            return {"stopped": True}
        step.status = "running"
        step.attempt += 1
        output.started_at = utcnow()
        output.error = None
        mission.status = name
        record_event(db, mission, "step.started", {"step": name, "attempt": step.attempt})
        if name == "matching" and run.failure_remaining > 0:
            run.failure_remaining -= 1
            step.status = "failed"
            output.error = "Simulated temporary matching failure"
            record_event(
                db,
                mission,
                "step.failed",
                {"step": name, "attempt": step.attempt, "error": output.error, "retryable": True},
            )
            return {"simulate_failure": True}
        return {"job_url": mission.job_url}


def finish_step(sessions, mission_id, run_number, name, payload, latency_ms):
    with sessions.begin() as db:
        mission = lock_mission(db, mission_id)
        run = db.get(MissionRun, mission_id)
        if mission.status in {"cancelled", "failed"} or not run or run.run_number != run_number:
            return {"stopped": True}
        step = db.scalar(
            select(MissionStep).where(MissionStep.mission_id == mission_id, MissionStep.name == name)
        )
        output = db.get(StepOutput, step.id)
        if step.status == "completed":
            return output.output
        if mission.status == "completed":
            return {"stopped": True}
        if name == "generating":
            model_calls = int(payload.get("_model_calls", 0))
            report, job, drafts = prepare_artifacts(db, mission_id, payload)
            # Serialize pipeline upserts for different missions targeting the same workspace/job.
            db.execute(
                update(Workspace).where(Workspace.id == mission.workspace_id).values(name=Workspace.name)
            )
            opportunity = db.scalar(
                select(Opportunity).where(
                    Opportunity.url == mission.job_url, Opportunity.workspace_id == mission.workspace_id
                )
            )
            if opportunity is None:
                opportunity = Opportunity(
                    id=str(uuid4()),
                    workspace_id=mission.workspace_id,
                    title=job.title,
                    company=job.company,
                    url=mission.job_url,
                )
                db.add(opportunity)
                db.flush()
            else:
                opportunity.title, opportunity.company = job.title, job.company
            application = db.scalar(
                select(Application).where(
                    Application.workspace_id == mission.workspace_id,
                    Application.opportunity_id == opportunity.id,
                )
            )
            if application is None:
                application = Application(
                    id=str(uuid4()),
                    workspace_id=mission.workspace_id,
                    opportunity_id=opportunity.id,
                    stage="saved",
                )
                db.add(application)
                db.flush()
                db.add(
                    StageHistory(
                        id=str(uuid4()),
                        application_id=application.id,
                        from_stage=None,
                        to_stage="saved",
                        note="Created from completed sample mission",
                    )
                )
            application.mission_id = mission_id
            application.fit_score = report.score
            application.company, application.title = job.company, job.title
            application.job_url, application.updated_at = mission.job_url, utcnow()
            artifact_ids = []
            for artifact_type, content in drafts.items():
                artifact = Artifact(
                    id=str(uuid4()),
                    mission_id=mission_id,
                    workspace_id=mission.workspace_id,
                    type=artifact_type,
                    version=1,
                    content=content.model_dump(mode="json"),
                    status="draft",
                )
                db.add(artifact)
                artifact_ids.append(artifact.id)
            payload = report.model_copy(update={"artifact_ids": artifact_ids}).model_dump(mode="json")
            run.result = payload
        output.output = payload
        output.completed_at = utcnow()
        output.latency_ms = latency_ms
        output.error = None
        step.status = "completed"
        record_event(
            db,
            mission,
            "step.completed",
            {
                "step": name,
                "attempt": step.attempt,
                "latency_ms": latency_ms,
                "execution_mode": "synthetic-fixture",
            },
        )
        if name == "generating":
            usage_count, usage_cost = db.execute(
                select(func.count(ModelCall.id), func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
                    ModelCall.mission_id == mission_id
                )
            ).one()
            mission.status = "completed"
            record_event(
                db,
                mission,
                "mission.completed",
                {
                    "score": payload["score"],
                    "execution_mode": "synthetic-fixture",
                    "model_calls": max(model_calls, int(usage_count)),
                    "cost_usd": round(float(usage_cost), 8),
                    "artifact_ids": payload["artifact_ids"],
                    "artifact_status": "draft",
                },
            )
        return payload


def fail_mission(sessions, mission_id, run_number, name):
    with sessions.begin() as db:
        mission = lock_mission(db, mission_id)
        run = db.get(MissionRun, mission_id)
        if mission.status in TERMINAL or run.run_number != run_number:
            return
        mission.status = "failed"
        # awaiting_approval is not a persisted MissionStep; skip step-level update.
        step = db.scalar(
            select(MissionStep).where(MissionStep.mission_id == mission_id, MissionStep.name == name)
        )
        error_msg = "Activity exhausted its retry limit. Retry from this checkpoint."
        if step is not None:
            step.status = "failed"
            output = db.get(StepOutput, step.id)
            if output:
                output.error = output.error or error_msg
                error_msg = output.error
        record_event(db, mission, "mission.failed", {"step": name, "error": error_msg})
