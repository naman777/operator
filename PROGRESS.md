# Operator implementation progress

Updated: 2026-09-19

## Current milestone
Durable workflow, profile correction/plain-text evidence ingestion, guarded static public-job imports, eligibility checks, and four cited drafts are implemented. Next: structured resume parsing, embeddings/semantic matching, browser extraction, and durable approvals.

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
- Python tests: **53 passed**, including a real isolated Temporal server, mid-run worker restart, retries, artifact provenance and replay, concurrent pipeline writes, authorization, and migrations.
- Ruff checks: passed for API, scripts, tests, and migration.
- Frontend formatting check: passed.
- TypeScript type checking: passed (enforced by Next.js build).
- Next.js production build: passed. Four frontend SSE parser/replay tests also passed.
- Docker Compose configuration parsing: passed.
- No model-quality metrics or workflow-completion metrics have been measured.

## In progress / next work
Phase 4 is in progress (plain-text ingestion and static public snapshots completed):
1. Extend profile ingestion to PDF/DOCX and parse resume into structured education, skills, experience, dates, and preferences.
2. Chunk and embed evidence with provenance (pgvector).
3. Feed real, source-backed job constraints and ingested profile data into the implemented deterministic eligibility checks.
4. Replace exact fixture skill matching with structured semantic matching while preserving the reproducible score and evidence matrix.
5. Extend the implemented cited template drafts with controlled model drafting and immutable revisions.
6. Add artifact revision/diff view; citation viewer is implemented.

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
| 13. Guest session expiry and reset | Done (token rotation, not data deletion) |
| 14. Evidence-backed artifact drafts and viewer | Done (synthetic templates, version 1) |
| 15. Explicit deterministic eligibility | Done; real extraction of constraints pending |

## Later phases
- Real Playwright extraction replacing fixture HTML.
- Agents SDK structured LLM matching, eligibility, and report generation.
- Durable Temporal approval signals (currently: immediate database writes only).
- Artifact revision editing, diffs, and model-generated drafting (cited template drafts are implemented).
- MCP server, mock calendar/email-draft connectors, and shared authorization policies.
- Public-deployment security controls, rate limits, budget enforcement, and failure simulation.
- Measured evaluation suite/dashboard, tracing, deployment, and recruiter polish.

## Blockers and limitations
- Docker CLI is installed, but its configured daemon at 127.0.0.1:8888 is unreachable; full container startup and PostgreSQL runtime integration remain unverified. Native Temporal integration is verified.
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

### Final validation for this continuation
- All 36 Python tests passed, including isolated live Temporal execution with artifact and pipeline assertions.
- Four frontend SSE tests, type checks, production build, and Ruff passed.
- Native development database backed up under ignored .local/backups before applying migrations 003 and 004.
- Full Docker execution and visual browser testing remain unverified; Compose syntax validates.

### Checkpoint: live artifact validation
- Extended the real Temporal integration test to assert four draft artifacts and correct pipeline metadata.
- Added scripts/smoke_workflow.py for the running web/API/worker stack.
- Full-stack HTTP smoke passed: guest session, proxy, dispatch, retry exhaustion, checkpoint recovery, SSE replay, four cited drafts, application pipeline, and cancellation.

### Checkpoint: runnable worker infrastructure
- Finished the Compose workflow-worker service with API health dependency and worker package inclusion in the image.
- Migration 003 now inspects existing columns instead of swallowing DDL errors; existing local-bootstrap migration adoption is tested.
- Native API, worker, and production web build restarted on the migrated database; existing local data retained.
- Compose configuration validates; PostgreSQL container runtime is still unverified.

## Continuation commit map
| Commit | Checkpoint |
| --- | --- |
| `a411c1e` | Explicit eligibility and cited draft contracts |
| `7365c14` | Deterministic eligibility rules and regression tests |
| `dca96e9` | Atomic evidence-backed artifacts and pipeline completion |
| `88af441` | Live inspector, eligibility details, and artifact citations |
| `6a7f5ab` | Real Temporal and full-stack HTTP artifact verification |
| `a39a99a` | Worker infrastructure and safe migration adoption |

Documentation updated with current startup commands, accurate limitations, and the next tasks. Changes are committed locally only; nothing was pushed or deployed.

## Phase 4 continuation: profile ingestion
- Completed workspace-persistent profile corrections with optimistic version checks and immutable source evidence.
- Added bounded plain-text document ingestion, checksum deduplication, line/character provenance, exact skill detection, and evidence listing.
- Workflow planning snapshots the workspace profile; retries reuse the same candidate context.
- Added migration 005, generated contracts, and profile correction/ingestion UI.
- Pending: PDF/DOCX ingestion, automatic structured education/history parsing, embeddings, browser extraction, model matching, durable approval waits, and deployment. Plain-text ingestion appends to demo evidence; it does not silently replace the synthetic candidate.

- Profile checkpoint validation: 38 Python tests passed including isolated live Temporal; frontend typecheck and production build passed.

- Profile UI checkpoint: editable name, graduation, location, authorization and experience; plain-text ingestion; evidence provenance viewer. TypeScript and production build passed.

## Public extraction continuation
- Implemented static HTTPS JobPosting JSON-LD ingestion with stored raw snapshots, retrieval timestamps, hashes, explicit requirement excerpts, and isolated import APIs.
- Guarded transport validates all DNS answers, pins the connection to a public IP while preserving TLS hostname verification, revalidates redirects, and limits bytes/redirects/socket duration. DNS resolution uses the OS resolver and is not independently time-bounded yet.
- Imported jobs run through the same checkpointed workflow. Planning snapshots both the job and workspace profile.
- Added import UI and updated inspector labels for retrieved sources.
- Scope: static JSON-LD only, exact evidence matching; no Playwright screenshots, model calls, embeddings, or automatic hard-constraint extraction yet. Requirement importance uses a conservative required default because structured pages often do not encode required/preferred distinction; extracted requirements require review.

- Extraction backend validation: 53 Python tests passed including isolated live Temporal. Transport guards and imported workflow coverage use controlled HTML/HTTP fixtures; live public-site compatibility remains unverified. Ruff passed.

- Backend checkpoint: `d17ecb8`. Profile checkpoints: `6c97e3e` and `e56a977`.

- Public import UI validation: four frontend tests, typecheck, formatting and production build passed. Import selection preserves the successfully retrieved URL even if the input changes afterward. Visual browser testing remains unverified.


### Continuation checkpoint map
- `6c97e3e`: persistent versioned profiles and source evidence.
- `e56a977`: profile correction and resume evidence UI.
- `d17ecb8`: guarded public job snapshot ingestion and workflow integration.
- `2695773`: public import UI and source-aware inspector.

Native database backed up before migrations 005/006; API, worker and dashboard restarted. Full-stack HTTP smoke passed (guest session, dispatch, retry recovery, SSE, four cited drafts, pipeline and cancellation). Local dashboard: http://127.0.0.1:3000. No changes pushed or deployed.
