# Operator implementation progress

Updated: 2026-09-18

## Current milestone
Application pipeline and approval inbox implemented; next slice is connecting the frontend run inspector to live step-level SSE events and starting Phase 4 (profile ingestion, real embeddings, deterministic eligibility checks, and structured LLM matching).

## Completed
- Read the full blueprint and inspected the initially empty repository.
- Created pnpm/Turborepo monorepo with Next.js 15, TypeScript, FastAPI, Pydantic, and SQLAlchemy.
- Versioned MissionInput, JobPosting, CandidateProfile, RequirementMatch, and MissionResult schemas.
- Exported JSON Schema v1, OpenAPI, and generated TypeScript API declarations.
- Implemented isolated guest sessions with hashed bearer tokens and workspace-scoped authorization.
- Implemented persistent draft mission creation, listing, retrieval, and ordered creation-event retrieval.
- Implemented atomic mission/event writes, workspace-scoped idempotency, and conflicting-payload rejection.
- Added database models and a frozen, repeatable initial migration for workspaces, missions, steps, events, opportunities, and applications.
- Added a PostgreSQL migration lock and pgvector extension setup; SQLite is available for local development/tests.
- Seeded one synthetic candidate, two evidence chunks, three job contracts, and three HTML snapshots.
- Built responsive Mission Control, new-mission form, Run Inspector, sample opportunities, and candidate evidence views.
- Added request IDs and structured JSON request logs without bearer tokens or request bodies.
- Added Compose configuration for web, API, PostgreSQL, Redis, Temporal dev server, and MinIO.
- Added GitHub Actions for Python lint/tests, generated-contract drift, frontend formatting/type checks, and production build.
- Added README setup instructions, product stories/scoring specification, architecture, initial threat model, and demo script.
- Implemented Temporal `OpportunityMissionWorkflow` with bounded fixture activities, checkpoint recovery, cancellation, retries, provenance verification, and stored reports.
- Added Docker-free local Temporal server launcher with persistent history in `.local/temporal`.
- Implemented authenticated SSE with committed-event replay, monotonic IDs, Last-Event-ID/after cursors, heartbeats, and terminal-run closure.
- Connected frontend run inspector to real step states via `useMissionRun` hook (SSE + polling).
- Added `Approval`, `StageHistory` models and expanded `Application` with company/title/job_url/timestamps; added `expires_at` to `Workspace`.
- Auto-upsert application in pipeline when generating step completes a mission.
- Added `GET /v1/applications`, `PATCH /v1/applications/{id}` (stage history tracked).
- Added `GET /v1/approvals`, `POST approve/reject` endpoints (workspace-scoped, idempotent).
- Added `POST /v1/guest-sessions/reset` (re-issues fresh token, same workspace).
- Guest sessions now expire after 24 h.
- Added migration 003 for new tables and expanded columns.
- Added Application Pipeline screen: color-coded stage cards, fit score display, stage progression buttons.
- Replaced Approval Inbox placeholder with live list; approve/reject buttons call the API.
- Added nav badge for pending approval count, pulse-dot animation for running missions.
- Added 5 integration tests for pipeline and approval endpoints.

## Validation performed
- Python integration tests: **17 passed** (pipeline list, stage patch, expiry, reset, cross-workspace isolation, streaming replay, cursor validation, runtime checkpoints, cancellation, idempotency, migrations).
- Ruff checks: passed for API, scripts, tests, and migration.
- Frontend formatting check: passed.
- TypeScript type checking: passed (enforced by Next.js build).
- Next.js production build: compiled successfully in 3.1s.
- Docker Compose configuration parsing: passed.
- No model-quality metrics or workflow-completion metrics have been measured.

## In progress / next work
Phase 4 is next:
1. Profile ingestion: parse resume into structured education, skills, experience, dates, and preferences.
2. Chunk and embed evidence with provenance (pgvector).
3. Implement deterministic eligibility checks (graduation year, location, authorization, experience bounds).
4. Implement requirement-to-evidence matrix with transparent weighted fit score.
5. Generate versioned artifacts: resume change set, cover letter, recruiter message, interview brief.
6. Add artifact diff view and citation viewer.

Remaining foundation tasks: Auth.js account sessions, Langfuse tracing wiring, and complete local-stack validation.

## First-sprint backlog mapping
| Plan ticket | Status |
| --- | --- |
| 1. Versioned core schemas | Done |
| 2. Monorepo and Compose dependencies | Partial: Langfuse deferred; containers not runtime-tested |
| 3. Initial migrations | Done (003 added for pipeline and approvals) |
| 4. Synthetic candidate and three snapshots | Done |
| 5. Static Mission Control and Run Inspector | Done; connected to live SSE |
| 6. Create/get mission endpoints | Done |
| 7. Temporal workflow with mocked activities | Done |
| 8. Playwright extraction | Pending |
| 9. Agents SDK matching | Pending |
| 10. Store/render real workflow result | Done (fixture); pending LLM-backed result |
| 11. Application pipeline backend + frontend | Done |
| 12. Approval inbox backend + frontend | Done |
| 13. Guest session expiry and reset | Done |

## Later phases
- Real Playwright extraction replacing fixture HTML.
- Agents SDK structured LLM matching, eligibility, and report generation.
- Durable Temporal approval signals (currently: immediate database writes only).
- Artifact generation/versioning and diff view.
- MCP server, mock calendar/email-draft connectors, and shared authorization policies.
- Public-deployment security controls, rate limits, budget enforcement, and failure simulation.
- Measured evaluation suite/dashboard, tracing, deployment, and recruiter polish.

## Blockers and limitations
- Docker CLI is installed, but its configured daemon at 127.0.0.1:8888 is unreachable; full container startup and PostgreSQL/Temporal integration remain unverified.
- Browser automation reported no available browser; visual rendering and click-through testing remain unverified. HTTP smoke tests are not a substitute for browser E2E tests.
- Guest credentials expire after 24 h; this build is local-only and must not be deployed publicly.
- Arbitrary job URLs are saved only; no real page fetches, model calls, or external actions in this build.

## Local handoff
- Web running at http://127.0.0.1:3000
- API docs at http://127.0.0.1:8000/docs
- Restart instructions are in README.md; local SQLite data persists in ignored operator.db.
- Module checkpoints are committed locally. No remote push or deployment was performed.

## Checkpoint policy
- Commit after meaningful, validated progress, grouped by module or cohesive behavior.
- Use descriptive conventional messages explaining the change; avoid catch-all commits.
- Stage explicit paths and inspect staged changes before committing.
- Update this progress file alongside subsequent implementation checkpoints with completed work, validation, and remaining tasks.
- Keep generated contracts with schema changes, and relevant tests with their implementation.
- Do not commit secrets, local databases, dependencies, or build outputs.

## Module checkpoints
| Commit | Module | Change |
| --- | --- | --- |
| `422dd8a` | Workspace | pnpm/Turborepo and Python project tooling |
| `d96bcaa` | Contracts | Versioned schemas, OpenAPI, and generated API types |
| `9e4b2ef` | Demo data | Synthetic candidate evidence and three job snapshots |
| `6f4529a` | API | Isolated guest missions, persistence, audit events, migrations, and tests |
| `c174a77` | Web | Mission dashboard, guest flow, and persisted run inspector |
| `98c2306` | Infrastructure | Docker stack and CI quality checks |
| `0b12aa7` | API | Replayable SSE with authenticated event streaming |
| `ae60073` | Worker | Temporal fixture workflow, recovery, and provenance checks |
| `8697749` | API | Transactional dispatch and durable mission checkpoints |
| `d15df99` | API | Application pipeline, approval inbox, and guest session expiry |
| `862c81a` | Web | Application pipeline screen, live approval inbox, mission status indicators |

## Current continuation
- Reviewed the new pipeline/approval commits and uncommitted artifact/eligibility work; preserving and completing that implementation.
- Baseline: 3 failures (SQLite artifact migration, invalid artifact result contract, and overly optimistic eligibility), 18 passes, 1 opt-in Temporal test skipped.
- In progress: explicit eligibility constraints; evidence-backed draft artifacts with atomic, idempotent persistence; generated contracts and inspector integration.

### Checkpoint: typed eligibility and artifact contracts
- Added explicit graduation/experience bounds, authorization alternatives, internship dates, and source-backed coverage metadata to job contracts.
- Candidate availability and unknown experience are represented explicitly.
- Artifact content now has typed citations, a generation-method label, and a required review flag.
- Regenerated JSON Schemas, OpenAPI, and TypeScript declarations. Combined backend validation currently passes 34 tests (live Temporal test remains opt-in).

### Checkpoint: deterministic eligibility
- Completed graduation, experience, exact location/authorization, and internship-window checks using supplied constraints only.
- Missing requirements stay unknown; remote preference no longer passes every on-site location. No graduation cutoff is inferred from a job title.
- Verification now checks eligibility explanations against reproduced results.
- Preserved the expanded synthetic profile. Validation: 12 analysis/eligibility tests passed.

### Checkpoint: evidence-backed draft artifacts
- Finished cover-letter, resume-suggestion, recruiter-message, and interview-brief drafts from completed extraction/matching/verification checkpoints.
- Draft claims quote stored evidence and carry source citations; unsupported example metrics and requirement-ID-derived skill names were removed.
- Persisted artifact IDs in both the report and generating-step output; atomic completion rolls back invalid reports.
- Added a unique artifact version index, repaired SQLite migration 004, and preserved completion results across acknowledgement replay.
- Pipeline upserts use real stored company/title fields, workspace-scoped opportunities, and a workspace lock for concurrent missions.
- Validation: 34 Python tests passed, one live Temporal test pending; includes four artifact integration tests and repeatable migrations.

### Checkpoint: live inspector and cited artifact viewer
- Finished and preserved the live SSE inspector with start/cancel/retry controls and failure simulation.
- Artifact and eligibility views now use generated API types; drafts show actual counts, review status, stored evidence citations, and required/candidate values.
- Added loading/error handling for artifact requests and clipboard feedback, plus stable selection by artifact ID.
- Validation: four frontend stream tests, TypeScript checks, and Next.js production build passed. Visual click-through remains unverified because no browser automation surface is available.
