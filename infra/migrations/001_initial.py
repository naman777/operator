"""Frozen initial schema snapshot. Do not import live application models."""

from datetime import datetime, timezone
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    stage: Mapped[str] = mapped_column(String, default="saved")
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)


def upgrade(connection):
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(connection)
