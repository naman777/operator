# Architecture

The first increment preserves the planned Next.js/FastAPI boundary. Next.js proxies `/api` to FastAPI so the browser uses one origin. The Python service owns the Pydantic contracts, workspace authorization, SQLAlchemy persistence, and transactional creation event.

PostgreSQL is the deployment database. SQLite is a dependency-light local/test option only. A versioned migration runner uses a PostgreSQL advisory lock; the first migration creates the initial six business tables. The initial migration contains a frozen schema snapshot so later model changes cannot alter its meaning.

Guest tokens are random bearer credentials; only SHA-256 hashes are stored. Each session gets its own workspace. Browser localStorage retains the session for reloads. This local prototype has no session expiry or rate limit and must not be exposed publicly.

Mission creation and its first event commit in one transaction. A workspace-scoped unique idempotency key prevents duplicate creation; conflicting payloads produce 409. Mission/event reads enforce ownership and return 404 for foreign IDs.

Temporal, Redis, and MinIO are provisioned in Compose for later work but are not called by this API yet. Langfuse is deferred until tracing is integrated, avoiding an unused multi-service deployment. No generated content is currently produced.

## Next execution boundary
API -> persisted mission -> Temporal workflow -> bounded activities -> persisted events -> Redis publication -> SSE. Before dispatch, add an outbox so database commit and workflow start cannot diverge. The worker must own state transitions, sequence allocation, activity idempotency, and budget enforcement.
