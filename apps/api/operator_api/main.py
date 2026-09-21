import asyncio
import http.client
import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from anyio import from_thread, to_thread
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import Error as PlaywrightError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .logging_config import configure_logging
from .rate_limits import Limit, DatabaseWindowLimiter
from .db import (
    APPLICATION_STAGES,
    Account,
    AccountSession,
    Approval,
    Application,
    Artifact,
    Base,
    Event,
    Mission,
    StageHistory,
    Workspace,
    StoredProfile,
    ProfileArchive,
    ImportedJob,
    EvalRun,
    ExternalAction,
    ModelCall,
    database,
    utcnow,
)
from .schemas import (
    OpportunityImport,
    ImportReceipt,
    JobReviewUpdate,
    DocumentInput,
    DocumentReceipt,
    ProfileUpdate,
    ProfileState,
    ProfileArchiveView,
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
    AccountCredentials,
    AccountDeviceView,
    PasswordChange,
    AccountSessionView,
    JobPosting,
    MissionInput,
    MissionView,
    StageUpdate,
    WorkspaceView,
    EvalRunRequest,
    EvalRunView,
    EvalComparison,
    ActionProposal,
    ApprovalProposalUpdate,
    ExternalActionView,
    ModelCallView,
    ObservabilitySummary,
)

from . import (
    runtime,
    streaming,
    profiles,
    extraction,
    document_parser,
    evaluations,
    connectors,
    browser_renderer,
    observability,
    accounts,
    workspace_export,
)

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

        _TEMPORAL_CLIENT = await asyncio.wait_for(
            Client.connect(os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233")),
            timeout=2,
        )
    except Exception as exc:
        logger.warning("Temporal unavailable; approval signals will be skipped: %s", type(exc).__name__)
        return None
    return _TEMPORAL_CLIENT


async def _signal_approval(workflow_id: str, approved: bool) -> None:
    """Signal a persisted approval decision from FastAPI's event loop."""
    client = await _get_temporal_client()
    if client is None:
        return
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("approval_resolved", approved)
    except Exception as exc:
        logger.warning("Approval signal failed: %s", type(exc).__name__)


def create_app(database_url=None, limit_overrides: dict[str, int] | None = None):
    engine, sessions = database(database_url)
    configured_limits = {
        "api": int(os.getenv("OPERATOR_API_REQUESTS_PER_MINUTE", "240")),
        "guest": int(os.getenv("OPERATOR_GUEST_SESSIONS_PER_HOUR", "20")),
        "mission": int(os.getenv("OPERATOR_MISSION_MUTATIONS_PER_MINUTE", "20")),
        "upload": int(os.getenv("OPERATOR_UPLOADS_PER_HOUR", "30")),
        "import": int(os.getenv("OPERATOR_IMPORTS_PER_HOUR", "20")),
    }
    configured_limits.update(limit_overrides or {})
    if any(value < 1 for value in configured_limits.values()):
        raise ValueError("Rate limits must be positive integers")
    limiter = DatabaseWindowLimiter(engine)
    api_limit = Limit("api", configured_limits["api"], 60)
    guest_limit = Limit("guest", configured_limits["guest"], 3600)
    mission_limit = Limit("mission", configured_limits["mission"], 60)
    upload_limit = Limit("upload", configured_limits["upload"], 3600)
    import_limit = Limit("import", configured_limits["import"], 3600)

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
        rate_headers = {}
        if request.url.path.startswith("/v1/"):
            authorization = request.headers.get("authorization", "")
            network_identity = request.client.host if request.client else "unknown"
            network_key = hashlib.sha256(network_identity.encode()).hexdigest()
            workspace_identity = (
                authorization[7:] if authorization.startswith("Bearer ") else network_identity
            )
            workspace_key = hashlib.sha256(workspace_identity.encode()).hexdigest()
            limits = [(api_limit, network_key)]
            if request.method == "POST" and request.url.path in {
                "/v1/guest-sessions",
                "/v1/accounts/login",
                "/v1/accounts/register",
                "/v1/accounts/password",
            }:
                limits.append((guest_limit, network_key))
            if request.method == "POST" and (
                request.url.path == "/v1/missions" or request.url.path.startswith("/v1/missions/")
            ):
                limits.append((mission_limit, workspace_key))
            if request.method == "POST" and request.url.path in {
                "/v1/profile/documents", "/v1/profile/documents/upload",
            }:
                limits.append((upload_limit, network_key))
            if request.method == "POST" and request.url.path == "/v1/opportunities/import":
                limits.append((import_limit, network_key))
            for limit, key in limits:
                try:
                    allowed, remaining, retry_after = await to_thread.run_sync(limiter.check, key, limit)
                except SQLAlchemyError:
                    logger.error("rate_limit_storage_unavailable", extra={"request_id": request_id})
                    return JSONResponse(
                        {"detail": "Request admission temporarily unavailable. Retry later."},
                        status_code=503, headers={"Retry-After": "5", "X-Request-ID": request_id},
                    )
                rate_headers = {
                    "X-RateLimit-Limit": str(limit.requests),
                    "X-RateLimit-Remaining": str(remaining),
                }
                if not allowed:
                    response = JSONResponse(
                        {"detail": "Rate limit exceeded. Retry later."},
                        status_code=429,
                        headers={**rate_headers, "Retry-After": str(retry_after)},
                    )
                    response.headers["X-Request-ID"] = request_id
                    logger.warning(
                        "rate_limit_exceeded",
                        extra={"request_id": request_id, "method": request.method, "limit": limit.name},
                    )
                    return response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        for name, value in rate_headers.items():
            response.headers[name] = value
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
        found = db.scalar(select(Workspace).where(Workspace.token_hash == digest, Workspace.account_id.is_(None)))
        if not found:
            account_session = db.scalar(
                select(AccountSession).where(
                    AccountSession.token_hash == digest,
                    AccountSession.revoked_at.is_(None),
                )
            )
            if account_session:
                expires = account_session.expires_at
                if expires.tzinfo is None:
                    from datetime import timezone as _tz

                    expires = expires.replace(tzinfo=_tz.utc)
                if expires >= utcnow():
                    found = db.get(Workspace, account_session.workspace_id)
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

    @app.get("/health/live")
    def liveness():
        return {"status": "ok"}

    def database_readiness():
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ok"}

    app.get("/health")(database_readiness)
    app.get("/health/ready")(database_readiness)

    @app.post("/v1/guest-sessions", response_model=GuestSession, status_code=201)
    def guest(db: DB, response: Response, demo: Annotated[bool, Query()] = False):
        token = secrets.token_urlsafe(32)
        ws = Workspace(
            id=str(uuid4()),
            name="Guest workspace",
            is_demo=demo,
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
        if ws.account_id:
            raise HTTPException(403, "Account workspaces cannot create guest credentials")
        token = secrets.token_urlsafe(32)
        ws.token_hash = hashlib.sha256(token.encode()).hexdigest()
        ws.expires_at = utcnow() + timedelta(hours=GUEST_TTL_HOURS)
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {"token": token, "workspace": ws}

    def account_session_response(db, account, ws, request):
        token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(days=30)
        db.add(
            AccountSession(
                id=str(uuid4()),
                account_id=account.id,
                user_agent=request.headers.get("user-agent", "")[:512] or None,
                workspace_id=ws.id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=expires_at,
            )
        )
        return {"token": token, "account": account, "workspace": ws, "expires_at": expires_at}

    @app.post("/v1/accounts/register", response_model=AccountSessionView, status_code=201)
    def register_account(body: AccountCredentials, ws: WS, db: DB, response: Response, request: Request):
        if ws.account_id:
            raise HTTPException(409, "Workspace already belongs to an account")
        email = body.email.strip().casefold()
        if db.scalar(select(Account).where(Account.email == email)):
            raise HTTPException(409, "Account already exists")
        account = Account(id=str(uuid4()), email=email, password_hash=accounts.hash_password(body.password))
        db.add(account)
        db.flush()
        ws.account_id = account.id
        # Claiming a workspace preserves its explicitly chosen demo or real-data mode.
        ws.expires_at = None
        ws.token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        result = account_session_response(db, account, ws, request)
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.post("/v1/accounts/login", response_model=AccountSessionView)
    def login_account(body: AccountCredentials, db: DB, response: Response, request: Request):
        account = db.scalar(select(Account).where(Account.email == body.email.strip().casefold()))
        if not account or not accounts.verify_password(body.password, account.password_hash):
            raise HTTPException(401, "Invalid email or password")
        ws = db.scalar(select(Workspace).where(Workspace.account_id == account.id))
        if not ws:
            raise HTTPException(409, "Account workspace is unavailable")
        result = account_session_response(db, account, ws, request)
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.post("/v1/accounts/logout", status_code=204)
    def logout_account(
        db: DB,
        ws: WS,
        authorization: Annotated[str | None, Header()] = None,
    ):
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        account_session = db.scalar(
            select(AccountSession).where(
                AccountSession.token_hash == digest,
                AccountSession.workspace_id == ws.id,
                AccountSession.revoked_at.is_(None),
            )
        )
        if not account_session:
            raise HTTPException(422, "Current session is not an account session")
        account_session.revoked_at = utcnow()
        db.commit()
        return Response(status_code=204)

    def require_account_session(db, ws, authorization):
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        current = db.scalar(
            select(AccountSession).where(
                AccountSession.token_hash == digest,
                AccountSession.account_id == ws.account_id,
                AccountSession.workspace_id == ws.id,
                AccountSession.revoked_at.is_(None),
                AccountSession.expires_at > utcnow(),
            )
        )
        if not current:
            raise HTTPException(403, "Sign in to an account to manage sessions")
        return current

    @app.get("/v1/accounts/sessions", response_model=list[AccountDeviceView])
    def list_account_sessions(
        db: DB, ws: WS, response: Response, authorization: Annotated[str | None, Header()] = None
    ):
        current = require_account_session(db, ws, authorization)
        response.headers["Cache-Control"] = "private, no-store"
        rows = db.scalars(
            select(AccountSession)
            .where(
                AccountSession.account_id == current.account_id,
                AccountSession.revoked_at.is_(None),
                AccountSession.expires_at > utcnow(),
            )
            .order_by(AccountSession.created_at.desc())
        ).all()
        return [
            {
                "id": row.id,
                "user_agent": row.user_agent,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "current": row.id == current.id,
            }
            for row in rows
        ]

    @app.delete("/v1/accounts/sessions/{session_id}", status_code=204)
    def revoke_account_session(
        session_id: str, db: DB, ws: WS, authorization: Annotated[str | None, Header()] = None
    ):
        current = require_account_session(db, ws, authorization)
        target = db.scalar(
            select(AccountSession).where(
                AccountSession.id == session_id,
                AccountSession.account_id == current.account_id,
            )
        )
        if not target:
            raise HTTPException(404, "Session not found")
        target.revoked_at = target.revoked_at or utcnow()
        db.commit()
        return Response(status_code=204)

    @app.post("/v1/accounts/sessions/revoke-others", status_code=204)
    def revoke_other_sessions(db: DB, ws: WS, authorization: Annotated[str | None, Header()] = None):
        current = require_account_session(db, ws, authorization)
        db.execute(
            update(AccountSession)
            .where(
                AccountSession.account_id == current.account_id,
                AccountSession.id != current.id,
                AccountSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        db.commit()
        return Response(status_code=204)

    @app.post("/v1/accounts/password", status_code=204)
    def change_password(
        body: PasswordChange, db: DB, ws: WS, authorization: Annotated[str | None, Header()] = None
    ):
        current = require_account_session(db, ws, authorization)
        account = db.get(Account, current.account_id)
        if not accounts.verify_password(body.current_password, account.password_hash):
            raise HTTPException(403, "Current password is incorrect")
        account.password_hash = accounts.hash_password(body.new_password)
        db.execute(
            update(AccountSession)
            .where(
                AccountSession.account_id == account.id,
                AccountSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        db.commit()
        return Response(status_code=204)

    @app.get("/v1/workspace", response_model=WorkspaceView)
    def current_workspace(ws: WS):
        return ws

    @app.get("/v1/workspace/export")
    def export_workspace(ws: WS, db: DB):
        return JSONResponse(
            jsonable_encoder(workspace_export.build_workspace_export(db, ws)),
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": 'attachment; filename="operator-workspace-export.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/v1/profile", response_model=CandidateProfile)
    def profile(ws: WS, db: DB):
        return profiles.load(db, ws.id, runtime.sample_profile)

    @app.get("/v1/profile/state", response_model=ProfileState)
    def profile_state(ws: WS, db: DB):
        stored = db.get(StoredProfile, ws.id)
        return {
            "profile": profiles.load(db, ws.id, runtime.sample_profile),
            "version": stored.version if stored else 0,
            "reviewed_version": stored.reviewed_version if stored else None,
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
        if (
            body.profile.evidence != current.evidence
            or body.profile.id != current.id
            or body.profile.synthetic != current.synthetic
            or body.profile.field_sources != current.field_sources
            or body.profile.field_evidence_ids != current.field_evidence_ids
        ):
            raise HTTPException(422, "Evidence, profile identity, and field sources are read-only.")
        if not ws.is_demo and not body.profile.name.strip():
            raise HTTPException(422, "Add your name before saving the profile.")
        sources = dict(current.field_sources)
        field_evidence_ids = dict(current.field_evidence_ids)
        editable_fields = (
            "name",
            "graduation_year",
            "locations",
            "skills",
            "work_authorization",
            "experience_years",
            "available_from",
            "available_until",
            "employment_type_preference",
        )
        changed_fields = [
            field for field in editable_fields if getattr(body.profile, field) != getattr(current, field)
        ]
        for field in changed_fields:
            sources[field] = "user-correction"
            field_evidence_ids.pop(field, None)
        updated = body.profile.model_copy(
            update={
                "field_sources": sources,
                "field_evidence_ids": field_evidence_ids,
                "parse_source": (
                    "user-correction"
                    if any(field in changed_fields for field in ("graduation_year", "experience_years"))
                    else current.parse_source
                ),
            }
        )
        if updated == current:
            return {
                "profile": current,
                "version": version,
                "reviewed_version": stored.reviewed_version if stored else None,
            }
        if stored is None:
            stored = StoredProfile(workspace_id=ws.id, version=1, content=updated.model_dump(mode="json"))
            db.add(stored)
        else:
            stored.content = updated.model_dump(mode="json")
            stored.version += 1
        db.commit()
        return {
            "profile": updated,
            "version": stored.version,
            "reviewed_version": stored.reviewed_version,
        }

    @app.post("/v1/profile/confirm", response_model=ProfileState)
    def confirm_profile(ws: WS, db: DB, expected_version: Annotated[int, Query(ge=1)]):
        profiles.lock(db, ws.id)
        stored = db.get(StoredProfile, ws.id, populate_existing=True)
        if not stored or stored.version != expected_version:
            raise HTTPException(409, "Profile changed. Reload before confirming.")
        current = CandidateProfile.model_validate(stored.content)
        if current.synthetic or not current.name.strip() or not current.evidence:
            raise HTTPException(409, "Add your name and source evidence before confirming.")
        stored.reviewed_version = stored.version
        db.commit()
        return {
            "profile": current,
            "version": stored.version,
            "reviewed_version": stored.reviewed_version,
        }

    def profile_change_allowed(db, workspace_id):
        active = db.scalar(
            select(Mission.id).where(
                Mission.workspace_id == workspace_id,
                Mission.status.notin_(("draft", "completed", "failed", "cancelled")),
            )
        )
        if active:
            raise HTTPException(409, "Wait for active missions to finish before changing profile mode.")

    @app.get("/v1/profile/archives", response_model=list[ProfileArchiveView])
    def profile_archives(ws: WS, db: DB):
        return db.scalars(
            select(ProfileArchive)
            .where(ProfileArchive.workspace_id == ws.id)
            .order_by(ProfileArchive.created_at.desc())
        ).all()

    @app.post("/v1/profile/start-fresh", response_model=ProfileState)
    def start_fresh_profile(ws: WS, db: DB, expected_version: Annotated[int, Query(ge=0)]):
        profiles.lock(db, ws.id)
        profile_change_allowed(db, ws.id)
        stored = db.get(StoredProfile, ws.id, populate_existing=True)
        version = stored.version if stored else 0
        if version != expected_version:
            raise HTTPException(409, "Profile changed. Reload before starting fresh.")
        current = profiles.load(db, ws.id, runtime.sample_profile)
        if not ws.is_demo and not current.synthetic:
            raise HTTPException(409, "This workspace already uses a real profile.")
        db.add(
            ProfileArchive(
                id=str(uuid4()),
                workspace_id=ws.id,
                content=current.model_dump(mode="json"),
                profile_version=version,
                was_demo=ws.is_demo,
            )
        )
        clean = profiles.empty(ws.id)
        if stored:
            stored.content = clean.model_dump(mode="json")
            stored.version += 1
        else:
            stored = StoredProfile(workspace_id=ws.id, version=1, content=clean.model_dump(mode="json"))
            db.add(stored)
        stored.reviewed_version = None
        ws.is_demo = False
        db.commit()
        return {"profile": clean, "version": stored.version, "reviewed_version": None}

    @app.post("/v1/profile/archives/{archive_id}/restore", response_model=ProfileState)
    def restore_profile(archive_id: str, ws: WS, db: DB, expected_version: Annotated[int, Query(ge=0)]):
        profiles.lock(db, ws.id)
        profile_change_allowed(db, ws.id)
        archived = db.scalar(
            select(ProfileArchive).where(
                ProfileArchive.id == archive_id, ProfileArchive.workspace_id == ws.id
            )
        )
        if not archived:
            raise HTTPException(404, "Profile archive not found")
        stored = db.get(StoredProfile, ws.id, populate_existing=True)
        version = stored.version if stored else 0
        if version != expected_version:
            raise HTTPException(409, "Profile changed. Reload before restoring.")
        current = profiles.load(db, ws.id, runtime.sample_profile)
        db.add(
            ProfileArchive(
                id=str(uuid4()),
                workspace_id=ws.id,
                content=current.model_dump(mode="json"),
                profile_version=version,
                was_demo=ws.is_demo,
            )
        )
        restored = CandidateProfile.model_validate(archived.content)
        if stored:
            stored.content = restored.model_dump(mode="json")
            stored.version += 1
        else:
            stored = StoredProfile(workspace_id=ws.id, version=1, content=restored.model_dump(mode="json"))
            db.add(stored)
        stored.reviewed_version = None
        ws.is_demo = archived.was_demo
        db.commit()
        return {"profile": restored, "version": stored.version, "reviewed_version": None}

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

    @app.delete("/v1/evidence/{evidence_id}", response_model=ProfileState)
    def delete_evidence(
        evidence_id: str,
        ws: WS,
        db: DB,
        expected_version: Annotated[int, Query(ge=0)],
    ):
        try:
            result = profiles.remove_evidence(
                db, ws.id, evidence_id, expected_version, runtime.sample_profile
            )
            db.commit()
            return result
        except LookupError as exc:
            db.rollback()
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from exc

    @app.get("/v1/demo/jobs", response_model=list[JobPosting])
    def jobs(ws: WS):
        if not ws.is_demo:
            return []
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
                        "message": "Mission saved. Start the run when ready.",
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
        mission = get_owned(db, ws, mission_id)
        if not ws.is_demo and mission.status == "draft":
            candidate = profiles.load(db, ws.id, runtime.sample_profile)
            stored = db.get(StoredProfile, ws.id)
            if candidate.synthetic or not candidate.name.strip() or not candidate.evidence:
                raise HTTPException(
                    409, "Complete your real profile and add resume evidence before starting."
                )
            if not stored or stored.reviewed_version != stored.version:
                raise HTTPException(409, "Review and confirm your profile before starting.")
            imported = db.scalar(
                select(ImportedJob)
                .where(
                    ImportedJob.workspace_id == ws.id,
                    ImportedJob.original_url == mission.job_url,
                )
                .order_by(ImportedJob.created_at.desc())
            )
            if not imported:
                raise HTTPException(409, "Import this public job in Opportunities before starting.")
            if imported.reviewed_version != imported.version:
                raise HTTPException(409, "Review and confirm this job's requirements before starting.")
            valid_through = JobPosting.model_validate(imported.posting).valid_through
            if valid_through and valid_through < datetime.now(timezone.utc).date():
                raise HTTPException(409, "This job posting has expired. Import a current posting.")
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
        if approval.status == "approved":
            return approval
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
        if approval.action_type in connectors.MODELS:
            existing_action = db.scalar(
                select(ExternalAction).where(ExternalAction.approval_id == approval.id)
            )
            if not existing_action:
                action = ExternalAction(
                    id=str(uuid4()),
                    workspace_id=ws.id,
                    mission_id=approval.mission_id,
                    approval_id=approval.id,
                    type=approval.action_type,
                    payload=connectors.validate(approval.action_type, approval.proposed_payload),
                )
                db.add(action)
                mission = db.get(Mission, approval.mission_id)
                runtime.record_event(
                    db,
                    mission,
                    "action.created",
                    {"action_id": action.id, "action_type": action.type, "provider": "mock"},
                )
        db.commit()
        # Send the Temporal signal after the DB commit so the signal is only
        # delivered once the approval is durably persisted.
        if workflow_id:
            from_thread.run(_signal_approval, workflow_id, True)
        return approval

    @app.patch("/v1/approvals/{approval_id}/proposal", response_model=ApprovalView)
    def edit_approval_proposal(approval_id: str, body: ApprovalProposalUpdate, db: DB, ws: WS):
        approval = get_approval(db, ws, approval_id)
        if approval.status != "pending":
            raise HTTPException(409, "Approval is no longer pending")
        if approval.action_type not in connectors.MODELS:
            raise HTTPException(409, "This approval proposal cannot be edited")
        try:
            approval.proposed_payload = connectors.validate(approval.action_type, body.proposed_payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
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
        workflow_id = approval.workflow_id
        db.commit()
        if workflow_id:
            from_thread.run(_signal_approval, workflow_id, False)
        return approval

    @app.post("/v1/actions/propose", response_model=ApprovalView, status_code=201)
    def propose_action(body: ActionProposal, db: DB, ws: WS):
        mission = get_owned(db, ws, body.mission_id)
        try:
            payload = connectors.validate(body.action_type, body.proposed_payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        approval = Approval(
            id=str(uuid4()),
            mission_id=mission.id,
            workspace_id=ws.id,
            action_type=body.action_type,
            proposed_payload=payload,
            risk_level=connectors.RISK[body.action_type],
            expires_at=utcnow() + timedelta(hours=24),
        )
        db.add(approval)
        runtime.record_event(
            db,
            mission,
            "approval.requested",
            {"approval_id": approval.id, "action_type": approval.action_type},
        )
        db.commit()
        return approval

    @app.get("/v1/actions", response_model=list[ExternalActionView])
    def list_actions(db: DB, ws: WS):
        return db.scalars(
            select(ExternalAction)
            .where(ExternalAction.workspace_id == ws.id)
            .order_by(ExternalAction.created_at.desc())
        ).all()

    @app.get("/v1/missions/{mission_id}/model-calls", response_model=list[ModelCallView])
    def model_calls(mission_id: str, db: DB, ws: WS):
        get_owned(db, ws, mission_id)
        return db.scalars(
            select(ModelCall).where(ModelCall.mission_id == mission_id).order_by(ModelCall.created_at)
        ).all()

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
            raise HTTPException(
                409, f"Version conflict: expected {old.version}, got {body.expected_version}."
            )
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
            ashby = extraction.ashby_target(str(body.url))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if ashby:
            try:
                final_url, html, posting = extraction.fetch_ashby(str(body.url))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except (OSError, http.client.HTTPException) as exc:
                raise HTTPException(422, "Ashby public job board could not be reached.") from exc
            screenshot = None
        else:
            final_url, html, posting, screenshot = import_structured_job(str(body.url))
        row = ImportedJob(
            id=str(uuid4()),
            workspace_id=ws.id,
            original_url=str(body.url),
            content_hash=hashlib.sha256(html.encode()).hexdigest(),
            posting=posting.model_dump(mode="json"),
            snapshot=html,
            screenshot=screenshot,
        )
        db.add(row)
        db.commit()
        return {
            "import_id": row.id,
            "original_url": row.original_url,
            "snapshot_sha256": row.content_hash,
            "posting": posting,
            "screenshot_available": screenshot is not None,
            "version": row.version,
            "reviewed_version": row.reviewed_version,
        }

    def import_structured_job(url):
        try:
            final_url, html = extraction.fetch(url)
        except ValueError as exc:
            message = str(exc)
            safe_prefixes = (
                "Only public HTTPS job pages",
                "Local, private, and reserved network destinations",
                "Job page returned HTTP ",
                "Job page retrieval timed out",
                "Job URL must return an HTML page",
                "Compressed responses are not supported",
                "Job page exceeds the 2 MB limit",
                "Job page exceeded the redirect limit",
                "Redirect has no destination",
            )
            detail = message if message.startswith(safe_prefixes) else "Job page could not be retrieved."
            raise HTTPException(422, detail) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise HTTPException(422, "Job page could not be reached over HTTPS.") from exc
        screenshot = None
        try:
            posting = extraction.parse(final_url, html)
        except ValueError:
            try:
                final_url, html, screenshot = browser_renderer.render(final_url)
            except ValueError as exc:
                raise HTTPException(
                    422,
                    "Browser rendering rejected this page. Try a public job-detail page on the same origin.",
                ) from exc
            except (OSError, PlaywrightError) as exc:
                raise HTTPException(
                    422,
                    "Job page could not be rendered. Try a public job-detail page with structured JobPosting data.",
                ) from exc
            try:
                posting = extraction.parse(final_url, html)
            except ValueError as exc:
                raise HTTPException(
                    422,
                    "No single structured JobPosting was found after rendering. Try a public job-detail page.",
                ) from exc
        return final_url, html, posting, screenshot

    @app.patch("/v1/opportunities/imports/{import_id}/review", response_model=ImportReceipt)
    def review_imported_job(import_id: str, body: JobReviewUpdate, db: DB, ws: WS):
        row = db.scalar(
            select(ImportedJob).where(ImportedJob.id == import_id, ImportedJob.workspace_id == ws.id)
        )
        if not row:
            raise HTTPException(404, "Imported job not found")
        if row.version != body.expected_version:
            raise HTTPException(409, "Job changed. Reload before reviewing.")
        posting = JobPosting.model_validate(row.posting)
        original = {item.id: item for item in posting.requirements}
        selected = {item.id: item.importance for item in body.requirements}
        if len(selected) != len(body.requirements) or not set(selected) <= set(original):
            raise HTTPException(422, "Review may only select extracted requirements.")
        revised = posting.model_copy(
            update={
                "requirements": [
                    item.model_copy(update={"importance": selected[item.id]})
                    for item in posting.requirements
                    if item.id in selected
                ],
                "eligibility_requirements": (
                    posting.eligibility_requirements if body.accept_eligibility else None
                ),
            }
        )
        next_version = row.version + 1
        changed = db.execute(
            update(ImportedJob)
            .where(
                ImportedJob.id == import_id,
                ImportedJob.workspace_id == ws.id,
                ImportedJob.version == body.expected_version,
            )
            .values(
                posting=revised.model_dump(mode="json"),
                version=next_version,
                reviewed_version=next_version,
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Job changed. Reload before reviewing.")
        screenshot_available = row.screenshot is not None
        db.commit()
        return {
            "import_id": import_id,
            "original_url": row.original_url,
            "snapshot_sha256": row.content_hash,
            "posting": revised,
            "screenshot_available": screenshot_available,
            "version": next_version,
            "reviewed_version": next_version,
        }

    @app.get("/v1/opportunities/imports/{import_id}/screenshot")
    def imported_job_screenshot(import_id: str, db: DB, ws: WS):
        row = db.scalar(
            select(ImportedJob).where(
                ImportedJob.id == import_id,
                ImportedJob.workspace_id == ws.id,
            )
        )
        if not row or not row.screenshot:
            raise HTTPException(404, "Screenshot not found")
        return Response(content=row.screenshot, media_type="image/png")

    # ---------------------------------------------------------------------------
    # Evaluation lab
    # ---------------------------------------------------------------------------

    @app.post("/v1/evals/runs", response_model=EvalRunView, status_code=201)
    def run_evaluation(body: EvalRunRequest, db: DB, ws: WS):
        try:
            metrics, case_results = evaluations.run(DATA.parents[1], body.dataset_version)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        row = EvalRun(
            id=str(uuid4()),
            workspace_id=ws.id,
            dataset_version=body.dataset_version,
            evaluator_version=evaluations.EVALUATOR_VERSION,
            metrics=metrics,
            case_results=case_results,
        )
        db.add(row)
        db.commit()
        return row

    @app.get("/v1/evals/runs", response_model=list[EvalRunView])
    def list_evaluations(db: DB, ws: WS):
        return db.scalars(
            select(EvalRun).where(EvalRun.workspace_id == ws.id).order_by(EvalRun.created_at.desc())
        ).all()

    @app.get("/v1/evals/runs/{eval_run_id}", response_model=EvalRunView)
    def get_evaluation(eval_run_id: str, db: DB, ws: WS):
        row = db.scalar(select(EvalRun).where(EvalRun.id == eval_run_id, EvalRun.workspace_id == ws.id))
        if not row:
            raise HTTPException(404, "Evaluation run not found")
        return row

    @app.get("/v1/evals/compare", response_model=EvalComparison)
    def compare_evaluations(baseline: str, candidate: str, db: DB, ws: WS):
        rows = db.scalars(
            select(EvalRun).where(
                EvalRun.workspace_id == ws.id,
                EvalRun.id.in_([baseline, candidate]),
            )
        ).all()
        by_id = {row.id: row for row in rows}
        if baseline not in by_id or candidate not in by_id:
            raise HTTPException(404, "Evaluation run not found")
        result = evaluations.compare(by_id[baseline].metrics, by_id[candidate].metrics)
        return {"baseline_id": baseline, "candidate_id": candidate, **result}

    @app.get("/v1/observability/summary", response_model=ObservabilitySummary)
    def observability_summary(db: DB, ws: WS):
        return observability.summary(db, ws.id)

    @app.get("/v1/opportunities/imports", response_model=list[ImportReceipt])
    def imports(db: DB, ws: WS):
        return [
            {
                "import_id": row.id,
                "original_url": row.original_url,
                "snapshot_sha256": row.content_hash,
                "posting": row.posting,
                "screenshot_available": row.screenshot is not None,
                "version": row.version,
                "reviewed_version": row.reviewed_version,
            }
            for row in db.scalars(
                select(ImportedJob)
                .where(ImportedJob.workspace_id == ws.id)
                .order_by(ImportedJob.created_at.desc())
            )
        ]

    return app


app = create_app()
