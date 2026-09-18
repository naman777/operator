import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .logging_config import configure_logging
from .db import APPLICATION_STAGES, Approval, Application, Base, Event, Mission, StageHistory, Workspace, database, utcnow
from .schemas import (
    ApprovalResolution,
    ApprovalView,
    ApplicationView,
    FailureSimulation,
    RunView,
    CandidateProfile,
    EventView,
    GuestSession,
    JobPosting,
    MissionInput,
    MissionView,
    StageUpdate,
    WorkspaceView,
)

from . import runtime, streaming

configure_logging()
logger = logging.getLogger("operator.api")
DATA = Path(os.getenv("OPERATOR_DATA_DIR", str(Path(__file__).resolve().parents[3] / "data" / "demo")))
GUEST_TTL_HOURS = 24


def create_app(database_url=None):
    engine, sessions = database(database_url)

    @asynccontextmanager
    async def lifespan(app):
        # Local bootstrap only; deployed Postgres uses the versioned migration runner.
        if engine.dialect.name == "sqlite":
            Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Operator API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000),
            },
        )
        return response

    def session():
        with sessions() as db:
            yield db

    DB = Annotated[Session, Depends(session)]

    def workspace(db: DB, authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Guest session required")
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        found = db.scalar(select(Workspace).where(Workspace.token_hash == digest))
        if not found:
            raise HTTPException(401, "Invalid guest session")
        if found.expires_at:
            from datetime import timezone as _tz
            exp = found.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_tz.utc)
            if exp < utcnow():
                raise HTTPException(401, "Guest session expired. Open a new workspace.")
        return found

    WS = Annotated[Workspace, Depends(workspace)]

    def get_owned(db, ws, mission_id):
        mission = db.scalar(select(Mission).where(Mission.id == mission_id, Mission.workspace_id == ws.id))
        if not mission:
            raise HTTPException(404, "Mission not found")
        return mission

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ok", "execution_mode": "synthetic-fixture"}

    @app.post("/v1/guest-sessions", response_model=GuestSession, status_code=201)
    def guest(db: DB, response: Response):
        token = secrets.token_urlsafe(32)
        ws = Workspace(
            id=str(uuid4()),
            name="Guest workspace",
            is_demo=True,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=utcnow() + timedelta(hours=GUEST_TTL_HOURS),
        )
        db.add(ws)
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"token": token, "workspace": ws}

    @app.post("/v1/guest-sessions/reset", response_model=GuestSession, status_code=201)
    def reset_guest(ws: WS, db: DB, response: Response):
        """Reset the current guest workspace: clear all missions and re-issue a fresh token."""
        token = secrets.token_urlsafe(32)
        ws.token_hash = hashlib.sha256(token.encode()).hexdigest()
        ws.expires_at = utcnow() + timedelta(hours=GUEST_TTL_HOURS)
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"token": token, "workspace": ws}

    @app.get("/v1/workspace", response_model=WorkspaceView)
    def current_workspace(ws: WS):
        return ws

    @app.get("/v1/profile", response_model=CandidateProfile)
    def profile(ws: WS):
        return CandidateProfile.model_validate_json((DATA / "candidate.json").read_text())

    @app.get("/v1/demo/jobs", response_model=list[JobPosting])
    def jobs(ws: WS):
        return [JobPosting.model_validate_json(p.read_text()) for p in sorted(DATA.glob("job-*.json"))]

    @app.post("/v1/missions", response_model=MissionView, status_code=201)
    def create_mission(
        body: MissionInput,
        db: DB,
        ws: WS,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
    ):
        def existing():
            return db.scalar(
                select(Mission).where(
                    Mission.workspace_id == ws.id, Mission.idempotency_key == idempotency_key
                )
            )

        def replay(found):
            if (found.job_url, found.goal, found.budget_usd) != (
                str(body.job_url),
                body.goal,
                body.budget_usd,
            ):
                raise HTTPException(409, "Idempotency key already used for a different mission")
            response.status_code = 200
            return found

        found = existing()
        if found:
            return replay(found)
        mission = Mission(
            id=str(uuid4()),
            workspace_id=ws.id,
            job_url=str(body.job_url),
            goal=body.goal,
            budget_usd=body.budget_usd,
            idempotency_key=idempotency_key,
        )
        db.add(mission)
        try:
            db.flush()
            db.add(
                Event(
                    id=str(uuid4()),
                    mission_id=mission.id,
                    sequence=1,
                    type="mission.created",
                    payload={
                        "status": "draft",
                        "message": "Mission saved. Start a sample run when ready.",
                    },
                )
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            found = existing()
            if found:
                return replay(found)
            raise
        return mission

    @app.get("/v1/missions", response_model=list[MissionView])
    def missions(db: DB, ws: WS):
        return db.scalars(
            select(Mission).where(Mission.workspace_id == ws.id).order_by(Mission.created_at.desc())
        ).all()

    @app.get("/v1/missions/{mission_id}", response_model=MissionView)
    def mission(mission_id: str, db: DB, ws: WS):
        return get_owned(db, ws, mission_id)

    @app.get("/v1/missions/{mission_id}/events", response_model=list[EventView])
    def events(mission_id: str, db: DB, ws: WS, after: Annotated[int, Query(ge=0)] = 0):
        get_owned(db, ws, mission_id)
        return db.scalars(
            select(Event)
            .where(Event.mission_id == mission_id, Event.sequence > after)
            .order_by(Event.sequence)
        ).all()

    @app.get(
        "/v1/missions/{mission_id}/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    def stream_events(
        mission_id: str,
        request: Request,
        db: DB,
        ws: WS,
        after: Annotated[int, Query(ge=0)] = 0,
        last_event_id: Annotated[int | None, Header(ge=0)] = None,
    ):
        get_owned(db, ws, mission_id)
        # Do not retain a transaction for the lifetime of a streaming connection.
        db.rollback()
        return StreamingResponse(
            streaming.stream(sessions, request, mission_id, max(after, last_event_id or 0)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    def control(mission_id, db, ws, action):
        get_owned(db, ws, mission_id)
        try:
            result = action()
            db.commit()
            return result
        except runtime.StateConflict as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/missions/{mission_id}/start", response_model=MissionView, status_code=202)
    def start(mission_id: str, db: DB, ws: WS):
        return control(mission_id, db, ws, lambda: runtime.start_mission(db, mission_id))

    @app.post("/v1/missions/{mission_id}/retry", response_model=MissionView, status_code=202)
    def retry(mission_id: str, db: DB, ws: WS):
        return control(mission_id, db, ws, lambda: runtime.start_mission(db, mission_id, retry=True))

    @app.post("/v1/missions/{mission_id}/cancel", response_model=MissionView)
    def cancel(mission_id: str, db: DB, ws: WS):
        return control(mission_id, db, ws, lambda: runtime.cancel_mission(db, mission_id))

    @app.post("/v1/missions/{mission_id}/simulate-failure", response_model=MissionView)
    def simulate(mission_id: str, body: FailureSimulation, db: DB, ws: WS):
        return control(mission_id, db, ws, lambda: runtime.simulate_failure(db, mission_id, body.mode))

    @app.get("/v1/missions/{mission_id}/run", response_model=RunView)
    def run(mission_id: str, db: DB, ws: WS):
        return runtime.run_view(db, get_owned(db, ws, mission_id))

    # ---------------------------------------------------------------------------
    # Application pipeline
    # ---------------------------------------------------------------------------

    @app.get("/v1/applications", response_model=list[ApplicationView])
    def applications(db: DB, ws: WS):
        return db.scalars(
            select(Application)
            .where(Application.workspace_id == ws.id)
            .order_by(Application.created_at.desc())
        ).all()

    @app.patch("/v1/applications/{application_id}", response_model=ApplicationView)
    def update_stage(application_id: str, body: StageUpdate, db: DB, ws: WS):
        app = db.scalar(
            select(Application).where(Application.id == application_id, Application.workspace_id == ws.id)
        )
        if not app:
            raise HTTPException(404, "Application not found")
        if body.stage not in APPLICATION_STAGES:
            raise HTTPException(422, f"Invalid stage. Choose from: {', '.join(APPLICATION_STAGES)}")
        old_stage = app.stage
        app.stage = body.stage
        app.updated_at = utcnow()
        db.add(StageHistory(
            id=str(uuid4()),
            application_id=app.id,
            from_stage=old_stage,
            to_stage=body.stage,
            note=body.note,
        ))
        db.commit()
        return app

    # ---------------------------------------------------------------------------
    # Approval inbox
    # ---------------------------------------------------------------------------

    @app.get("/v1/approvals", response_model=list[ApprovalView])
    def approvals(db: DB, ws: WS, status: Annotated[str | None, Query()] = None):
        stmt = select(Approval).where(Approval.workspace_id == ws.id)
        if status:
            stmt = stmt.where(Approval.status == status)
        return db.scalars(stmt.order_by(Approval.created_at.desc())).all()

    def get_approval(db, ws, approval_id):
        found = db.scalar(
            select(Approval).where(Approval.id == approval_id, Approval.workspace_id == ws.id)
        )
        if not found:
            raise HTTPException(404, "Approval not found")
        return found

    @app.post("/v1/approvals/{approval_id}/approve", response_model=ApprovalView)
    def approve(approval_id: str, body: ApprovalResolution, db: DB, ws: WS):
        approval = get_approval(db, ws, approval_id)
        if approval.status != "pending":
            raise HTTPException(409, "Approval is no longer pending")
        if approval.expires_at:
            from datetime import timezone as _tz
            exp = approval.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_tz.utc)
            if exp < utcnow():
                raise HTTPException(409, "Approval has expired")
        approval.status = "approved"
        approval.resolved_at = utcnow()
        approval.resolved_by = "user"
        db.commit()
        return approval

    @app.post("/v1/approvals/{approval_id}/reject", response_model=ApprovalView)
    def reject(approval_id: str, body: ApprovalResolution, db: DB, ws: WS):
        approval = get_approval(db, ws, approval_id)
        if approval.status != "pending":
            raise HTTPException(409, "Approval is no longer pending")
        approval.status = "rejected"
        approval.resolved_at = utcnow()
        approval.resolved_by = "user"
        db.commit()
        return approval

    return app


app = create_app()
