# Operator implementation progress

Updated: 2026-09-20

### Checkpoint: guarded Agents SDK enrichment
- Added an explicitly enabled, tool-free Agents SDK adapter with typed structured outputs for semantic explanation review and cited application drafting.
- Deterministic eligibility, fit scores, statuses, and evidence mappings remain authoritative and reproducible; model output cannot introduce IDs or change those decisions.
- Model drafts require known evidence citations, reject source-absent numeric claims, keep immutable citations and review status, and fall back to existing templates on configuration, provider, or validation failure.
- Model execution requires a key, explicit model name, opt-in flag, and per-mission budget reserve. Live provider validation remains pending because no API key is configured.
- Durable completion events record attempted model calls, including calls whose output was rejected in favor of the deterministic fallback.
- Validation: 91 Python tests passed (one opt-in Temporal test skipped), Ruff passed, four frontend tests passed, and TypeScript checks passed. The installed Agents SDK accepted the configured typed Agent and one-turn Runner interface.

### Checkpoint: source-backed model requirement parsing
- Added structured model extraction in the worker after guarded retrieval and JSON-LD validation. It can supplement sparse JSON-LD with required/preferred requirements and explicit hard constraints.
- Every accepted requirement and constraint must reference an exact retrieved-source excerpt. IDs are generated locally; source-absent numbers, dates, authorization values, and invented requirements are discarded.
- Untrusted page text is isolated as data, model tools remain disabled, and provider/schema failures preserve the original JSON-LD posting. Extraction attempts are included in the mission's durable model-call count.
- Validation: 93 Python tests passed (one opt-in Temporal test skipped), Ruff passed, four frontend tests passed, TypeScript checks passed, and the installed Agents SDK accepted the job-parser output schema. Live provider validation remains pending because no API key is configured.

### Checkpoint: durable model usage and budget accounting
- Added migration 012 and workspace-scoped model-call audit records with stage, model, status, input/output tokens, configured cost, and timestamp.
- Agents SDK calls now request usage, cap output tokens, enforce a timeout, and calculate cost from explicitly configured per-million-token rates. Later stages use the mission budget minus recorded cost and retain the existing per-call reserve.
- Added `GET /v1/missions/{mission_id}/model-calls`; completion events now report persisted call count and cost instead of placeholders. Generated OpenAPI, JSON Schemas, and TypeScript declarations include the audit contract.
- Validation: 95 Python tests passed (one opt-in Temporal test skipped), migration repeatability and workspace isolation passed, Ruff and formatting passed, four frontend tests and TypeScript checks passed, and the production web build passed. Live provider validation remains pending because no API key is configured.
- Backed up the ignored local SQLite database and applied migrations through 012; the model-call table is available to the current development stack.

### Checkpoint: pgvector evidence retrieval
- Added migration 013 and relational evidence chunks containing source provenance, detected skills, and 256-dimensional deterministic feature-hash embeddings.
- PostgreSQL retrieval uses pgvector cosine distance and an HNSW cosine index. SQLite uses equivalent in-process cosine ranking so local tests and development require no external model or database service.
- Resume ingestion writes documents, profile evidence, and vectors atomically. The matching step snapshots top evidence per requirement before running the existing deterministic rubric; profiles without indexed chunks retain the full-evidence fallback.
- Validation: 96 Python tests passed (one opt-in Temporal test skipped), migration repeatability and concurrent ingestion passed, Ruff and formatting passed, four frontend tests and TypeScript checks passed, the production web build passed, and Compose configuration parsed successfully. PostgreSQL runtime execution remains pending because the configured Docker daemon is unavailable.
- Backed up the ignored local SQLite database and applied migration 013; newly ingested evidence now enters the local vector index.

### Checkpoint: evidence lifecycle and vector backfill
- Implemented the planned workspace-scoped `DELETE /v1/evidence/{evidence_id}` API with optimistic profile-version checks and atomic removal from both stored profile evidence and the vector index.
- Added migration 014 to backfill index rows for evidence ingested before migration 013 while preserving document, location, skill, and workspace provenance. Synthetic evidence without a stored source document remains on the safe full-profile fallback.
- Regenerated OpenAPI and TypeScript declarations. Validation: 97 Python tests passed (one opt-in Temporal test skipped), migration repeatability, stale-version conflicts, workspace isolation, and vector deletion passed; Ruff, formatting, four frontend tests, TypeScript checks, and the production build passed.
- Backed up the ignored local SQLite database and applied migration 014. The current database had no eligible stored-document chunks to backfill; future ingestion is indexed immediately.

## Current milestone
The local portfolio release now includes guarded browser extraction, source-backed model parsing and drafting, pgvector retrieval, a 40-case deterministic evaluation suite, per-process API admission controls, and durable dispatch dead letters. Next release blockers are account authentication, shared multi-replica rate enforcement, managed secret integration, and a verified staging restore/deployment.

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
1. ~~Extend profile ingestion to PDF/DOCX and parse resume into structured education, skills, experience, dates, and preferences.~~ **Done.**
2. ~~Chunk and embed evidence with provenance (pgvector / semantic matching).~~ **Done** (deterministic token-overlap; pgvector deferred until Docker stack is available).
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

## Phase 4/5 continuation: sourced constraints, approval waits, and artifact revisions
- Public JSON-LD imports now copy explicit experience, graduation, work-authorization, and internship-window constraints into the typed eligibility model with source provenance. Application deadlines are kept separate from internship dates and are never treated as eligibility evidence.
- Resume ingestion deterministically extracts graduation year and dated work-history duration while preserving user corrections and recording whether a value came from synthetic data, a correction, or heuristic parsing.
- Opportunity workflows now pause durably after verification, create one idempotent approval record, and resume from a Temporal signal. Approval, rejection, and timeout transitions are stored as mission events; rejection and timeout cancel the mission instead of leaving it stuck awaiting approval.
- Draft artifacts can be edited into immutable revisions. Each save creates the next version, marks the prior version superseded, and retains version history in the run inspector.
- Added migrations 007/008 for approval workflow routing and artifact revision links; migrations remain repeatable on existing SQLite databases.
- Validation: 77 Python tests passed plus the isolated real Temporal integration test; Ruff, generated-contract type checking, four frontend tests, Prettier, and the Next.js production build passed.

## Phase 4 continuation: PDF/DOCX resume upload ingestion
- Added `pypdf`, `python-docx`, and `python-multipart` as production dependencies.
- Added `apps/api/operator_api/document_parser.py`: `extract_pdf(bytes)` and `extract_docx(bytes)` work entirely in-memory via `io.BytesIO`; no temp files; both raise `ValueError` with a user-safe message on failure.
- Added `POST /v1/profile/documents/upload` multipart endpoint: 5 MB limit, PDF/DOCX format detection by extension and magic bytes, same `DocumentReceipt` response as the text endpoint, feeds directly into the existing `profiles.ingest()` pipeline including heuristic structural parsing (graduation year, experience years, skill detection, line/char provenance, checksum deduplication).
- Added drag-and-drop / click-to-browse file upload zone to the profile editor: idle, uploading (pulse animation), done (evidence count), and error states.
- Added upload zone CSS to `globals.css`.
- Validation: 64 Python tests passed (7 new upload tests: PDF happy path, DOCX happy path, oversized 413, unsupported type 422, deduplication, structural parse from PDF, auth guard). Ruff clean. TypeScript typecheck clean. Next.js production build passed.

### Continuation checkpoint map
- `6c97e3e`: persistent versioned profiles and source evidence.
- `e56a977`: profile correction and resume evidence UI.
- `d17ecb8`: guarded public job snapshot ingestion and workflow integration.
- `2695773`: public import UI and source-aware inspector.
- `0a19447`: PDF and DOCX resume upload ingestion and file upload UI.
- `fc0ea48`: semantic token-overlap evidence matching.

## Phase 4 continuation: Semantic token-overlap evidence matching
- Added `services/workflow-worker/operator_worker/matcher.py`: `tokenize()` (stopword removal + lightweight suffix stripping), `jaccard()`, `score_requirement()` (exact skill-list fast path + token-overlap fallback). Pure Python stdlib, no new dependencies.
- Rewrote `analysis.py` `match()`: exact skill-list exact match → `supported` (fast path, fixture-compatible); Jaccard ≥ 0.40 → `supported`; Jaccard ≥ 0.15 → `partial` (40% weight contribution); below → `missing`. Fit score reflects both tiers.
- Updated `verify()`: accepts `partial` status alongside `supported`; restores `"Unsupported positive match"` error string for backwards compatibility with existing security tests.
- Validation: 77 tests passed (13 new: 4 tokenizer/Jaccard units, 5 score_requirement units, 3 match+verify integration, 1 fixture-compat). Ruff clean. No new dependencies.

## Phase 6 continuation: measured Evaluation Lab
- Added the versioned `opportunity-v1` dataset with three exact-fit and documented-gap cases using the synthetic candidate and existing job fixtures.
- Added deterministic graders for requirement accuracy, score mean absolute error, citation coverage, unsupported positive rate, and matcher latency. Verification reuses the production provenance and reproducibility checks.
- Persisted workspace-scoped evaluation runs and case results through migration 009.
- Added run, list, detail, and baseline/candidate comparison APIs. Comparisons flag quality regressions while reporting latency separately.
- Replaced the Evaluation Lab placeholder with live run controls, metric cards, history, and case-level pass/fail results.
- Updated README, product specification, and demo script to remove stale claims about completed ingestion and approval work.
- Validation: 80 Python tests passed, Ruff passed, four frontend tests passed, TypeScript and Prettier checks passed, and the Next.js production build completed successfully.

## Phase 5 continuation: authenticated MCP service
- Added an MCP v2 stdio server with bounded tools for mission creation/status, pending approvals, approval resolution, and pipeline reads.
- MCP calls delegate to the existing HTTP API so workspace ownership, validation, idempotency, and Temporal approval signaling are shared with the dashboard.
- The workspace bearer token is supplied only through `OPERATOR_TOKEN`; it is never a tool parameter or model-visible schema field.
- Added safe API-error translation, a local console entry point, sample MCP host configuration, and adapter tests covering authorization headers, idempotency, routes, invalid decisions, and sanitized failures.
- Pinned MCP 2.2 and compatible SSE support; widened Uvicorn to the MCP-compatible supported range.
- Validation: 83 Python tests passed, Ruff passed, the initial five MCP v2 tools registered successfully, and inspected input schemas contain no token field.

## Phase 5 continuation: approval-controlled mock connectors
- Added typed email-draft and calendar-event proposals with deterministic validation and low/medium risk classification.
- Pending connector payloads can be edited as JSON in the Approval Inbox; invalid recipients, unknown fields, and reversed calendar windows are rejected before approval.
- Approval materializes one idempotent, workspace-scoped `mock` action and records an `action.created` mission event. Email is never sent and no real calendar is contacted.
- Added list/propose action APIs, migration 010, generated contracts, and a sixth MCP tool for proposing connector actions through the same authorization boundary.
- Integration coverage includes edit-before-approve, rejection, repeat approval, action idempotency, validation, and workspace isolation.
- Validation: 85 Python tests passed, Ruff passed, four frontend tests passed, TypeScript and formatting checks passed, and the Next.js production build compiled successfully.

## Phase 2/4 continuation: guarded Playwright extraction
- Static pinned-IP HTTPS extraction remains the fast path. Pages without a server-rendered JobPosting now fall back to headless Chromium.
- Browser navigation is restricted to the original validated public HTTPS hostname; private/reserved destinations, cross-origin requests, images, fonts, media, and other nonessential resource types are aborted.
- Rendering has a 20-second navigation timeout, a 2 MB HTML limit, a 5 MB screenshot limit, blocked service workers, and host resolver pinning for the original hostname.
- Browser-rendered HTML becomes the stored source snapshot. PNG screenshots are stored in the workspace, served through an authenticated endpoint, and previewed after import.
- Added migration 011, Playwright runtime dependency, generated contracts, browser-launch smoke coverage, fallback persistence tests, request-guard tests, and workspace-isolation checks.
- API/worker container builds now include the MCP package required by project metadata and install Chromium with its system dependencies.
- Validation: real headless Chromium launch and screenshot smoke passed; 87 Python tests, Ruff, four frontend tests, TypeScript, formatting, and the Next.js production build passed.

## Phase 4 continuation: cited official-company research
- Added a durable `researching` checkpoint between extraction and matching. It follows only an explicit HTTPS company URL from the job posting and reuses the guarded, pinned-IP transport.
- Extracted claims are bounded to exact meta-description and Organization JSON-LD excerpts. Every claim must reference a stored source; retrieval failures and postings without an official URL safely produce an empty research result.
- Company research is carried into the final mission result, displayed with source links and retrieval times in the run inspector, and included in artifact citations and interview preparation.
- Artifact generation verifies the research result against the completed checkpoint before saving drafts, preventing injected or changed research claims.
- Validation: 100 Python tests passed with the opt-in live Temporal test skipped; Ruff, generated contracts, four frontend tests, Prettier, TypeScript, and the Next.js production build passed.

## Phase 7 continuation: expanded deterministic evaluation
- Preserved the original three-case `opportunity-v1` baseline and added `opportunity-v2` with fifteen cases across matching, weak evidence, partial matches, weighted scoring, prompt-injection text, eligibility failures, eligibility ambiguity, and incomplete extraction.
- Evaluation cases can apply isolated job and candidate overrides while still passing through the production Pydantic contracts, matcher, verifier, and eligibility engine.
- Added case pass rate and eligibility accuracy, category labels, expected/actual eligibility results, and regression detection for the new quality metrics. Historical stored runs remain readable and comparable.
- Updated Evaluation Lab to run v2 by default and display pass rate, eligibility accuracy, categories, and eligibility outcomes.
- Validation: 102 Python tests passed with the opt-in live Temporal test skipped; Ruff, generated contracts, four frontend tests, Prettier, TypeScript, and the Next.js production build passed.

## Phase 8 start: recruiter-facing demo guide
- Reworked the guest entry into a clear three-step guided demo without adding signup or external-account dependencies.
- Added an in-product Project Guide with direct demo navigation, a readable system architecture flow, implemented safeguards, and explicit local-MVP limitations.
- Added responsive layouts for the demo steps, guide cards, architecture flow, and safety/limitation panels, plus recruiter-facing page metadata.
- Desktop (1440x1000) and mobile (390x844) landing-page screenshots were rendered with local Playwright and visually inspected. The bundled Windows computer-use runtime was unavailable because its configured Node runtime path could not be found.
- Validation: 102 Python tests passed with the opt-in live Temporal test skipped; Ruff, four frontend tests, Prettier, TypeScript, and the Next.js production build passed.

## Phase 8 continuation: deployment readiness
- Added separate `/health/live` and database-backed `/health/ready` endpoints while preserving `/health` compatibility.
- Added `compose.production.yaml` for immutable API/web images, a one-shot migration dependency, managed PostgreSQL and Temporal endpoints, health-gated startup, restart policies, no-new-privileges, temporary filesystems, and loopback web binding behind a TLS proxy.
- Added a production environment template with placeholder-only values and an operations runbook covering prerequisites, configuration validation, rollout, rollback, database/Temporal recovery, provider outages, and required alerts. CI now rejects invalid production Compose changes.
- Production Compose configuration resolves successfully without contacting the unavailable Docker daemon. Public deployment remains blocked on production authentication, rate limiting, secret management, and staging restore verification.
- Validation: production Compose config passed; 102 Python tests passed with the opt-in live Temporal test skipped; Ruff, generated contracts, four frontend tests, Prettier, TypeScript, and the Next.js production build passed.

## Phase 8 continuation: direct-production CI/CD
- Added a personal-project single-host production stack for EC2: Caddy with automatic HTTPS, web, API, worker, PostgreSQL/pgvector, and persistent single-node Temporal. Only ports 80/443 are published by Compose.
- Extended GitHub Actions from CI into gated CD. Successful `main` or manual builds publish immutable API/web images to GHCR; deployment stays disabled until the repository variable `PRODUCTION_ENABLED=true`.
- The production job uses a protected GitHub environment, pinned SSH host keys, environment-scoped host configuration, server-resident secrets, pre-deploy PostgreSQL dumps, migration-gated startup, container health checks, and a public HTTPS smoke check.
- Added a placeholder-only single-host environment template and documented EC2 sizing, DNS, firewall, Docker/GHCR setup, GitHub variables/secrets, backups, and the single-node Temporal durability limitation.
- No cloud account, host, DNS record, repository environment, or secret has been configured from this checkout; those external prerequisites are required before the first deployment.

## Phase 6/7 continuation: admission controls, dead letters, and 40-case evaluation
- Added configurable sliding-window limits for general API traffic, guest-session creation, and mission mutations. Identifiers are one-way hashed, raw tokens and client addresses are not retained, responses include `Retry-After` and rate-limit headers, and the in-memory key set is bounded.
- Mission limits are workspace-token scoped while the general and guest limits remain client-address scoped so rotating an invalid bearer value cannot bypass general admission control. The built-in limiter is explicitly a single-process layer; public multi-replica deployment still requires a shared edge or distributed limiter.
- Added migration 015 and terminal dead-letter state for workflow dispatch commands. Exhausted commands stop retrying, store only the error class, emit one durable `mission.dispatch_dead_lettered` event, and failed starts move the mission to a visible failed state without duplicating side effects.
- Added inherited `opportunity-v3`, expanding the deterministic evaluation suite from 15 to 40 unique cases across exact and weak evidence, weighted scoring, prompt injection, graduation, experience, authorization, internship dates, ambiguity, and missing role location.
- Evaluation runs now record P50 and P95 matcher latency. The Evaluation Lab defaults to v3 and preserves v1/v2 as comparable historical baselines.
- Updated generated OpenAPI/TypeScript contracts, production environment controls, Compose wiring, architecture/threat/deployment documentation, and recruiter-facing descriptions.
- Backed up the ignored local SQLite database and applied migration 015; the current development database now exposes the dispatch dead-letter state.
- Validation: 105 Python tests passed with one opt-in live Temporal test skipped; Ruff passed; four frontend tests, TypeScript, Prettier, and the Next.js production build passed; production Compose configuration resolved successfully.
