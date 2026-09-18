"""Application pipeline, approval inbox, and guest session expiry; frozen schema snapshot."""

from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, String, Table, Column, text, inspect
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
    # Inspect first: catching duplicate-column errors would abort PostgreSQL's transaction.
    additions = {
        "workspaces": {"expires_at": "TIMESTAMP WITH TIME ZONE"},
        "applications": {
            "mission_id": "TEXT REFERENCES missions(id)",
            "company": "TEXT",
            "title": "TEXT",
            "job_url": "TEXT",
            "updated_at": "TIMESTAMP WITH TIME ZONE",
            "created_at": "TIMESTAMP WITH TIME ZONE",
        },
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in inspect(connection).get_columns(table)}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
    connection.execute(
        text(
            "UPDATE applications SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
            "updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)"
        )
    )
    Base.metadata.create_all(connection, tables=[StageHistory.__table__, Approval.__table__])
