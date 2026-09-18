import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .logging_config import configure_logging
from .db import Base, Event, Mission, Workspace, database
from .schemas import (
    FailureSimulation,
    RunView,
    CandidateProfile,
    EventView,
    GuestSession,
    JobPosting,
    MissionInput,
    MissionView,
    WorkspaceView,
)

from . import runtime

configure_logging()
logger = logging.getLogger("operator.api")
DATA = Path(os.getenv("OPERATOR_DATA_DIR", str(Path(__file__).resolve().parents[3] / "data" / "demo")))


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
        )
        db.add(ws)
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
    def events(mission_id: str, db: DB, ws: WS, after: int = 0):
        get_owned(db, ws, mission_id)
        return db.scalars(
            select(Event)
            .where(Event.mission_id == mission_id, Event.sequence > after)
            .order_by(Event.sequence)
        ).all()

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

    return app


app = create_app()
