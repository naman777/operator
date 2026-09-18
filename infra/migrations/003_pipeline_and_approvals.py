"""Application pipeline, approval inbox, and guest session expiry; frozen schema snapshot."""

from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, String, Table, Column, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# Reference-only stubs so FKs resolve during create_all.
Table("workspaces", Base.metadata, Column("id", String, primary_key=True))
Table("missions", Base.metadata, Column("id", String, primary_key=True))
Table("opportunities", Base.metadata, Column("id", String, primary_key=True))
Table("applications", Base.metadata, Column("id", String, primary_key=True))


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
    action_type: Mapped[str] = mapped_column(String)
    proposed_payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending")
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def upgrade(connection):
    # Add expires_at to workspaces (idempotent: ignore if column exists).
    try:
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN expires_at TIMESTAMP WITH TIME ZONE"))
    except Exception:
        pass  # Already exists on PostgreSQL; SQLite will re-run create_all.

    # Expand applications table.
    for col_sql in [
        "ALTER TABLE applications ADD COLUMN mission_id TEXT REFERENCES missions(id)",
        "ALTER TABLE applications ADD COLUMN company TEXT",
        "ALTER TABLE applications ADD COLUMN title TEXT",
        "ALTER TABLE applications ADD COLUMN job_url TEXT",
        "ALTER TABLE applications ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE applications ADD COLUMN created_at TIMESTAMP WITH TIME ZONE",
    ]:
        try:
            connection.execute(text(col_sql))
        except Exception:
            pass

    Base.metadata.create_all(connection, tables=[StageHistory.__table__, Approval.__table__])
