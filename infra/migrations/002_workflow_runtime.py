"""Durable dispatch and activity checkpoints; frozen schema snapshot."""

from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Table, Column
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


Table("missions", Base.metadata, Column("id", String, primary_key=True))
Table("mission_steps", Base.metadata, Column("id", String, primary_key=True))


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


def upgrade(connection):
    Base.metadata.create_all(
        connection, tables=[MissionRun.__table__, StepOutput.__table__, DispatchCommand.__table__]
    )
