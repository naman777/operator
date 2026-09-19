import os
from datetime import datetime, timezone
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Mission(Base):
    __tablename__ = "missions"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    job_url: Mapped[str] = mapped_column(String)
    goal: Mapped[str] = mapped_column(String)
    budget_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="draft")
    idempotency_key: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MissionStep(Base):
    __tablename__ = "mission_steps"
    __table_args__ = (UniqueConstraint("mission_id", "name"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"))
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("mission_id", "sequence"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    title: Mapped[str] = mapped_column(String)
    company: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("workspace_id", "opportunity_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"))
    mission_id: Mapped[str | None] = mapped_column(ForeignKey("missions.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String, default="saved")
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    job_url: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


APPLICATION_STAGES = ("saved", "applied", "interview", "offer", "rejected")


class StageHistory(Base):
    __tablename__ = "stage_history"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    to_stage: Mapped[str] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    action_type: Mapped[str] = mapped_column(String)  # e.g. "pipeline_update", "send_email"
    proposed_payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, approved, rejected
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Temporal workflow handle ID; set when the workflow is waiting for the signal.
    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_level: Mapped[str] = mapped_column(String, default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_mission_type_version", "mission_id", "type", "version", unique=True),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    type: Mapped[str] = mapped_column(
        String
    )  # cover_letter, resume_suggestions, recruiter_message, interview_brief
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | final | superseded
    # ID of the artifact that replaced this version; null for the latest revision.
    superseded_by: Mapped[str | None] = mapped_column(String, ForeignKey("artifacts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MissionRun(Base):
    __tablename__ = "mission_runs"
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), primary_key=True)
    run_number: Mapped[int] = mapped_column(Integer, default=1)
    failure_remaining: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class StepOutput(Base):
    __tablename__ = "step_outputs"
    step_id: Mapped[str] = mapped_column(ForeignKey("mission_steps.id"), primary_key=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class DispatchCommand(Base):
    __tablename__ = "dispatch_commands"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    workflow_id: Mapped[str] = mapped_column(String)
    command: Mapped[str] = mapped_column(String)
    run_number: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StoredProfile(Base):
    __tablename__ = "profiles"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    content: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ProfileDocument(Base):
    __tablename__ = "profile_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    checksum: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("workspace_id", "checksum"),)


class ImportedJob(Base):
    __tablename__ = "imported_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    original_url: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    posting: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    dataset_version: Mapped[str] = mapped_column(String)
    evaluator_version: Mapped[str] = mapped_column(String)
    metrics: Mapped[dict] = mapped_column(JSON)
    case_results: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalAction(Base):
    __tablename__ = "external_actions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), unique=True)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String, default="mock")
    status: Mapped[str] = mapped_column(String, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def database(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./operator.db")
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine, sessionmaker(engine, expire_on_commit=False)
