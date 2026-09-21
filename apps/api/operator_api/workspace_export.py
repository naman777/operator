"""User-facing workspace archive with an explicit, credential-free field list."""

import base64

from sqlalchemy import select

from .db import (
    Account,
    Application,
    Approval,
    Artifact,
    EvalRun,
    Event,
    ExternalAction,
    ImportedJob,
    Mission,
    MissionRun,
    MissionStep,
    ModelCall,
    Opportunity,
    ProfileArchive,
    ProfileDocument,
    StageHistory,
    StepOutput,
    StoredProfile,
    utcnow,
)


def _records(db, model, fields, *filters):
    return [
        {field: getattr(row, field) for field in fields}
        for row in db.scalars(select(model).where(*filters)).all()
    ]


def build_workspace_export(db, workspace):
    """Export user inputs, decisions and results; never serialize ORM objects wholesale."""
    missions = _records(
        db, Mission,
        ("id", "job_url", "goal", "budget_usd", "status", "created_at"),
        Mission.workspace_id == workspace.id,
    )
    mission_ids = [row["id"] for row in missions]
    steps = _records(
        db, MissionStep, ("id", "mission_id", "name", "status", "attempt"),
        MissionStep.mission_id.in_(mission_ids),
    )
    applications = _records(
        db, Application,
        ("id", "opportunity_id", "mission_id", "stage", "fit_score", "company", "title", "job_url", "created_at", "updated_at"),
        Application.workspace_id == workspace.id,
    )
    imported_jobs = _records(
        db, ImportedJob,
        ("id", "original_url", "content_hash", "posting", "snapshot", "screenshot", "version", "reviewed_version", "created_at"),
        ImportedJob.workspace_id == workspace.id,
    )
    for job in imported_jobs:
        screenshot = job.pop("screenshot")
        job["screenshot_base64"] = base64.b64encode(screenshot).decode("ascii") if screenshot else None

    profile = db.get(StoredProfile, workspace.id)
    account = db.get(Account, workspace.account_id) if workspace.account_id else None
    return {
        "format_version": 1,
        "exported_at": utcnow(),
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "is_demo": workspace.is_demo,
            "account_email": account.email if account else None,
        },
        "profile": (
            {"content": profile.content, "version": profile.version, "reviewed_version": profile.reviewed_version}
            if profile else None
        ),
        "profile_archives": _records(
            db, ProfileArchive,
            ("id", "content", "profile_version", "was_demo", "created_at"),
            ProfileArchive.workspace_id == workspace.id,
        ),
        "documents": _records(
            db, ProfileDocument, ("id", "name", "checksum", "text", "created_at"),
            ProfileDocument.workspace_id == workspace.id,
        ),
        "imported_jobs": imported_jobs,
        "missions": missions,
        "mission_runs": _records(
            db, MissionRun, ("mission_id", "run_number", "result"),
            MissionRun.mission_id.in_(mission_ids),
        ),
        "mission_steps": steps,
        "step_outputs": _records(
            db, StepOutput, ("step_id", "output", "started_at", "completed_at", "latency_ms", "error"),
            StepOutput.step_id.in_([row["id"] for row in steps]),
        ),
        "events": _records(
            db, Event, ("id", "mission_id", "sequence", "type", "payload", "created_at"),
            Event.mission_id.in_(mission_ids),
        ),
        "approvals": _records(
            db, Approval,
            ("id", "mission_id", "action_type", "proposed_payload", "status", "resolved_by", "resolved_at", "expires_at", "risk_level", "created_at"),
            Approval.workspace_id == workspace.id,
        ),
        "artifacts": _records(
            db, Artifact,
            ("id", "mission_id", "type", "version", "content", "status", "superseded_by", "created_at"),
            Artifact.workspace_id == workspace.id,
        ),
        "opportunities": _records(
            db, Opportunity, ("id", "title", "company", "url"),
            Opportunity.workspace_id == workspace.id,
        ),
        "applications": applications,
        "stage_history": _records(
            db, StageHistory, ("id", "application_id", "from_stage", "to_stage", "changed_at", "note"),
            StageHistory.application_id.in_([row["id"] for row in applications]),
        ),
        "external_actions": _records(
            db, ExternalAction, ("id", "mission_id", "approval_id", "type", "payload", "provider", "status", "created_at"),
            ExternalAction.workspace_id == workspace.id,
        ),
        "model_calls": _records(
            db, ModelCall, ("id", "mission_id", "step", "model", "input_tokens", "output_tokens", "cost_usd", "status", "created_at"),
            ModelCall.mission_id.in_(mission_ids),
        ),
        "evaluation_runs": _records(
            db, EvalRun, ("id", "dataset_version", "evaluator_version", "metrics", "case_results", "created_at"),
            EvalRun.workspace_id == workspace.id,
        ),
    }
