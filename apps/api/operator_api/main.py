import http.client
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

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .logging_config import configure_logging
from .db import (
    APPLICATION_STAGES,
    Approval,
    Application,
    Artifact,
    Base,
    Event,
    Mission,
    StageHistory,
    Workspace,
    StoredProfile,
    ImportedJob,
    database,
    utcnow,
)
from .schemas import (
    OpportunityImport,
    ImportReceipt,
    DocumentInput,
    DocumentReceipt,
    ProfileUpdate,
    ProfileState,
    Evidence,
    ApprovalResolution,
    ApprovalView,
    ApplicationView,
    ArtifactUpdate,
    ArtifactView,
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

from . import runtime, streaming, profiles, extraction, document_parser

configure_logging()
logger = logging.getLogger("operator.api")
DATA = Path(os.getenv("OPERATOR_DATA_DIR", str(Path(__file__).resolve().parents[3] / "data" / "demo")))
GUEST_TTL_HOURS = 24
_TEMPORAL_CLIENT = None


async def _get_temporal_client():
    """Lazy Temporal client singleton; falls back gracefully if the server is unreachable."""
    global _TEMPORAL_CLIENT
    if _TEMPORAL_CLIENT is not None:
        return _TEMPORAL_CLIENT
    try:
        from temporalio.client import Client
        from datetime import timedelta as _td
        _TEMPORAL_CLIENT = await Client.connect(
            os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
            rpc_timeout=_td(seconds=2),
        )
    except Exception as exc:
        logger.warning("Temporal unavailable; approval signals will be skipped: %s", type(exc).__name__)
        return None
    return _TEMPORAL_CLIENT


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
    def profile(ws: WS, db: DB):
        return profiles.load(db, ws.id, runtime.sample_profile)

    @app.get("/v1/profile/state", response_model=ProfileState)
    def profile_state(ws: WS, db: DB):
        stored = db.get(StoredProfile, ws.id)
        return {
            "profile": profiles.load(db, ws.id, runtime.sample_profile),
            "version": stored.version if stored else 0,
        }

    @app.patch("/v1/profile", response_model=ProfileState)
    def correct_profile(body: ProfileUpdate, ws: WS, db: DB):
        profiles.lock(db, ws.id)
        stored = db.get(StoredProfile, ws.id, populate_existing=True)
        version = stored.version if stored else 0
        if body.expected_version != version:
            raise HTTPException(409, "Profile changed. Reload before saving.")
        current = profiles.load(db, ws.id, runtime.sample_profile)
        # Profile corrections cannot rewrite or fabricate source excerpts.
        if body.profile.evidence != current.evidence or body.profile.id != current.id:
            raise HTTPException(
                422, "Evidence and profile identity are read-only; ingest source documents instead."
            )
        if stored is None:
            stored = StoredProfile(
                workspace_id=ws.id, version=1, content=body.profile.model_dump(mode="json")
            )
            db.add(stored)
        else:
            stored.content = body.profile.model_dump(mode="json")
            stored.version += 1
        db.commit()
        return {"profile": body.profile, "version": stored.version}

    @app.post("/v1/profile/documents", response_model=DocumentReceipt, status_code=201)
    def ingest_document(body: DocumentInput, ws: WS, db: DB):
        try:
            receipt = profiles.ingest(db, ws.id, body, runtime.sample_profile)
            db.commit()
            return receipt
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc

    _MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

    @app.post("/v1/profile/documents/upload", response_model=DocumentReceipt, status_code=201)
    async def upload_document(
        ws: WS,
        db: DB,
        file: UploadFile = File(...),
        name: str | None = None,
    ):
        """Upload a PDF or DOCX resume and ingest its extracted text as evidence."""
        raw = await file.read(_MAX_UPLOAD_BYTES + 1)
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File exceeds the 5 MB limit. Please reduce the file size.")
        filename = file.filename or "upload"
        fmt = document_parser.detect_format(filename, raw)
        if fmt is None:
            raise HTTPException(
                422,
                "Unsupported file type. Only PDF (.pdf) and DOCX (.docx) files are accepted.",
            )
        try:
            if fmt == "pdf":
                text = document_parser.extract_pdf(raw)
            else:
                text = document_parser.extract_docx(raw)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        doc_name = (name or filename)[:200]
        body = DocumentInput(name=doc_name, text=text)
        try:
            receipt = profiles.ingest(db, ws.id, body, runtime.sample_profile)
            db.commit()
            return receipt
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/evidence", response_model=list[Evidence])
    def evidence(ws: WS, db: DB):
        return profiles.load(db, ws.id, runtime.sample_profile).evidence

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
        db.add(
            StageHistory(
                id=str(uuid4()),
                application_id=app.id,
                from_stage=old_stage,
                to_stage=body.stage,
                note=body.note,
            )
        )
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
        found = db.scalar(select(Approval).where(Approval.id == approval_id, Approval.workspace_id == ws.id))
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
        workflow_id = approval.workflow_id
        db.commit()
        # Send the Temporal signal after the DB commit so the signal is only
        # delivered once the approval is durably persisted.
        if workflow_id:
            import asyncio

            async def _signal():
                client = await _get_temporal_client()
                if client:
                    try:
                        handle = client.get_workflow_handle(workflow_id)
                        await handle.signal("approval_resolved", True)
                    except Exception as exc:
                        logger.warning("Approval signal failed: %s", type(exc).__name__)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_signal())
                else:
                    loop.run_until_complete(_signal())
            except Exception as exc:
                logger.warning("Could not dispatch approval signal: %s", type(exc).__name__)
        return approval

    @app.post("/v1/approvals/{approval_id}/reject", response_model=ApprovalView)
    def reject(approval_id: str, body: ApprovalResolution, db: DB, ws: WS):
        approval = get_approval(db, ws, approval_id)
        if approval.status != "pending":
            raise HTTPException(409, "Approval is no longer pending")
        approval.status = "rejected"
        approval.resolved_at = utcnow()
        approval.resolved_by = "user"
        workflow_id = approval.workflow_id
        db.commit()
        if workflow_id:
            import asyncio

            async def _signal():
                client = await _get_temporal_client()
                if client:
                    try:
                        handle = client.get_workflow_handle(workflow_id)
                        await handle.signal("approval_resolved", False)
                    except Exception as exc:
                        logger.warning("Rejection signal failed: %s", type(exc).__name__)

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_signal())
                else:
                    loop.run_until_complete(_signal())
            except Exception as exc:
                logger.warning("Could not dispatch rejection signal: %s", type(exc).__name__)
        return approval

    # ---------------------------------------------------------------------------
    # Artifacts
    # ---------------------------------------------------------------------------

    @app.get("/v1/missions/{mission_id}/artifacts", response_model=list[ArtifactView])
    def mission_artifacts(mission_id: str, db: DB, ws: WS):
        get_owned(db, ws, mission_id)
        return db.scalars(
            select(Artifact)
            .where(Artifact.mission_id == mission_id, Artifact.workspace_id == ws.id)
            .order_by(Artifact.created_at)
        ).all()

    @app.get("/v1/artifacts/{artifact_id}", response_model=ArtifactView)
    def artifact(artifact_id: str, db: DB, ws: WS):
        found = db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.workspace_id == ws.id))
        if not found:
            raise HTTPException(404, "Artifact not found")
        return found

    @app.patch("/v1/artifacts/{artifact_id}", response_model=ArtifactView)
    def revise_artifact(artifact_id: str, body: ArtifactUpdate, db: DB, ws: WS):
        """Submit a revised draft. Creates a new versioned artifact and marks the old one superseded."""
        old = db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.workspace_id == ws.id))
        if not old:
            raise HTTPException(404, "Artifact not found")
        if old.status == "superseded":
            raise HTTPException(409, "Cannot revise a superseded artifact. Use the latest version.")
        if body.expected_version != old.version:
            raise HTTPException(409, f"Version conflict: expected {old.version}, got {body.expected_version}.")
        new_artifact = Artifact(
            id=str(uuid4()),
            mission_id=old.mission_id,
            workspace_id=ws.id,
            type=old.type,
            version=old.version + 1,
            content=body.content.model_dump(mode="json"),
            status="draft",
        )
        db.add(new_artifact)
        db.flush()
        old.superseded_by = new_artifact.id
        old.status = "superseded"
        db.commit()
        return new_artifact

    @app.post("/v1/opportunities/import", response_model=ImportReceipt, status_code=201)
    def import_job(body: OpportunityImport, db: DB, ws: WS):
        try:
            final_url, html = extraction.fetch(str(body.url))
            posting = extraction.parse(final_url, html)
        except (ValueError, OSError, http.client.HTTPException) as exc:
            raise HTTPException(422, "Could not import a supported public HTTPS JobPosting page.") from exc
        row = ImportedJob(
            id=str(uuid4()),
            workspace_id=ws.id,
            original_url=str(body.url),
            content_hash=hashlib.sha256(html.encode()).hexdigest(),
            posting=posting.model_dump(mode="json"),
            snapshot=html,
        )
        db.add(row)
        db.commit()
        return {"import_id": row.id, "posting": posting}

    @app.get("/v1/opportunities/imports", response_model=list[ImportReceipt])
    def imports(db: DB, ws: WS):
        return [
            {"import_id": row.id, "posting": row.posting}
            for row in db.scalars(
                select(ImportedJob)
                .where(ImportedJob.workspace_id == ws.id)
                .order_by(ImportedJob.created_at.desc())
            )
        ]

    return app


app = create_app()
