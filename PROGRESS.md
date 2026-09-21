# Operator project progress

Updated: 2026-09-21

## Current state

Operator is deployed at https://operator.naman.sbs on the existing Google Compute Engine VM. The public readiness endpoint returned HTTP 200 with valid TLS on 2026-09-21. GitHub Actions runs quality checks, publishes commit-SHA API and web images to GHCR, and is configured to deploy eligible main-branch pushes to production. This is a live, working portfolio application, but its default experience is still a guided demo with synthetic candidate and job data. Do not describe it as an autonomous job-application service.

## Current unreleased work

The next release is being developed locally and is not yet on the public site. Authenticated workspaces can download a JSON archive of their saved profile, resume text, imported job snapshots and screenshots, missions, approval decisions, artifacts, pipeline history, and model-use records; credentials and session tokens are excluded. New guest workspaces default to real-data mode with an empty profile; the guided demo is an explicit choice. Real-data workspaces hide fixture jobs and require a named profile with user-ingested evidence and an imported public job. Users must confirm the current profile version and review the latest job import before starting a real-data mission. The profile editor records source labels per field, links inferred graduation year, experience, and skills to exact stored resume excerpts, and supports skills, availability dates, and employment-type preferences. Deleting cited evidence clears inferred values that have lost support. The job review can discard unsupported extracted requirements, mark retained requirements required or preferred, and exclude questionable hard constraints while preserving the original source snapshot. Posting and expiry dates are shown when present; an expired posting cannot start a real-data mission. Repeat imports compare the immutable source snapshot hash and warn when bytes differ, even if the difference may be incidental page markup. Public JobPosting pages that put requirements in explicitly labeled description lists have a bounded source-backed extraction fallback. Current public Ashby postings use Ashby's read-only public board API through pinned HTTPS; the importer matches the requested job URL exactly and rejects removed postings without opening cross-origin browser assets. Import errors distinguish unreachable or missing pages, rendering problems, and pages without a single structured JobPosting. Profile edits and new evidence invalidate profile confirmation; a new import requires a new review. Claiming a guest workspace as an account preserves its chosen mode. An explicit start-fresh action archives an existing synthetic profile, keeps mission history, and can restore the archived profile; active missions block mode changes. Archived evidence remains stored but is excluded from retrieval for the new profile. Integration tests cover these review checkpoints, imported-job analysis, artifact generation, archive isolation, and restoration. Existing production data and volumes have not been changed; migrations 017 and 018 and this code are local only.

## Next-phase account security milestone (local only)

- Added an Account security panel for authenticated users in Mission Control: active browser/session labels, creation and expiry times, individual sign-out, sign-out of all other sessions, and password change with current-password verification. Password changes revoke every account session, including the caller. Browser labels are untrusted user-agent strings, not verified device identities; no IP address or fingerprint is stored.
- Session APIs require an active account session, hide expired/revoked sessions, enforce account isolation, and never return token hashes. Guest reset is forbidden for claimed workspaces, and legacy guest credentials cannot authenticate to an account-owned workspace.
- Migration 019 adds nullable browser labels without changing existing sessions or production data. Apply all pending migrations before deploying this release.
- Added independent dependency-audit CI jobs for Python and JavaScript on pull requests, main pushes, weekly schedules, and manual runs. The main quality workflow now calls the audit workflow and image publication requires both audits and quality checks to pass. Scan failures are not suppressed.
- The local JavaScript audit found four PostCSS advisories. A workspace override pins PostCSS 8.5.23; the updated lockfile passes `pnpm audit` with no known vulnerabilities.
- The Python scan identified vulnerable Starlette and pypdf constraints. Updated to tested FastAPI 0.141.1, Starlette 1.6.0, and pypdf 6.19.0 release ranges. The complete regression suite passed 128 tests with two optional skips in an isolated environment using those releases, and `pip check` reported no broken requirements. The final strict audit of installed third-party Python dependencies reported no known vulnerabilities; regenerated API contracts passed frontend TypeScript validation.
- Validation: four frontend tests, TypeScript, Ruff, formatting, and the production build passed. Migration 019 passed repeatable SQLite migration and bootstrap-adoption checks. Live PostgreSQL and browser interaction checks were not run locally.
- These changes advance Phase 4; they do not complete the remaining phases. Email verification/recovery, deletion/retention, provider OAuth/actions, consented real-input quality measurement, and production recovery exercises remain outstanding. No production deployment or external provider action was performed.

## Release hardening (ready for deployment)

- PostgreSQL-backed atomic fixed-window counters share limits across API processes and restarts. Migration 020 adds only hashed admission identifiers, counters, and expiry timestamps. Expired rows are removed in batches during requests. Storage failure returns 503 with Retry-After and does not admit expensive work; health probes remain available.
- Resume text/file ingestion is limited to 30 attempts per client network per hour, and public-job imports to 20, independently of the general request and mission limits. Production Compose exposes both settings. These are application admission controls, not an edge WAF or DDoS service; fixed windows permit boundary bursts and shared networks share quotas.
- Added a public `/privacy` data-storage notice describing current exports, session controls, archived data, third-party processing, and the absence of automatic data deletion or password recovery. This is an operational notice, not a claim of legal compliance or a completed deletion/retention policy.
- Security audit jobs now gate image publication and deployment, with a separate weekly scheduled run retained.
- Release checks: 132 Python tests passed, two optional tests skipped locally; four frontend tests, lint, formatting, TypeScript, and generated contracts passed. Production build and CI PostgreSQL/Temporal checks are verified during release. Existing production records and volumes will be preserved.

## What works today

- Next.js dashboard and FastAPI API: guest workspaces, first-party registration/login, workspace isolation, mission creation, live run inspection, approval inbox, application pipeline, artifact viewer, evaluation lab, operations dashboard, and project guide.
- Persistent mission execution: PostgreSQL-backed application state on Aiven, a separate PostgreSQL-backed production Temporal service on the VM, outbox dispatch, checkpointed activities, retries, cancellation, event replay, and worker restart recovery.
- Human approval: the authenticated FastAPI approve/reject endpoints persist decisions and signal the waiting Temporal workflow; approved missions continue to generation. Approval and workflow regression coverage exists.
- Real input paths: PDF/DOCX or text resume evidence ingestion; corrections to structured profile fields; guarded HTTPS import of supported public JobPosting pages with a same-origin Playwright fallback, saved source snapshots, and optional cited official-company research.
- Analysis and output: deterministic eligibility and scoring, stored evidence citations, pgvector-backed evidence retrieval on PostgreSQL, four reviewable application drafts with immutable revisions, and a saved pipeline entry. No application is submitted.
- Optional guarded model enrichment for source-backed requirement extraction, explanation review, and cited drafting. The deterministic score, eligibility, and evidence mapping remain authoritative. Model use requires an explicit enable flag, model, key, and budget; live provider quality is not yet established.
- Workspace-scoped model-call audit, a 40-case deterministic evaluation dataset, request admission controls, dispatch dead letters, and operational metrics.
- Public HTTPS through Caddy. Only HTTP/HTTPS are published; API, worker, Temporal, and PostgreSQL remain on private Docker networks. Production Compose includes health checks, persistent storage, restart policies, and VM-sized limits.
- CI/CD validates Python, contracts, frontend, builds, and Compose; publishes immutable images; and runs a health-gated production deployment from main when production repository variables allow it. The latest deployment validated in the prior rollout used commit cac2939252fab3073d870481328520e0c8493251.

## Validation for the unreleased real-data milestone

- 125 Python tests passed; two optional tests were skipped locally, including the fresh-PostgreSQL migration test that runs in CI with its PostgreSQL service.
- Four frontend tests, TypeScript checks, frontend formatting, Ruff lint checks, generated contracts, and the Next.js production build passed.
- Integration tests cover an empty real workspace through resume evidence, profile confirmation, imported-job review, mission planning, artifact generation, and account claim without seeded facts. Review tests cover stale versions, workspace isolation, discarded requirements, confirmation invalidation, independent field sources, cited evidence deletion, expired postings, and distinct import errors. Archive tests cover active-mission blocking, restoration, and retained mission history.
- Read-only live compatibility checks parsed five source-backed requirements from a Lever detail page and 12 from a currently published Ashby job via its public board API. A removed Ashby URL was rejected as no longer published. A sampled Greenhouse embed URL returned HTTP 404. These observations do not establish broad site compatibility.
- No production migration, image publication, or deployment has been performed for this milestone.

## Why the product still looks like a mock

- The deployed version still falls back to data/demo/candidate.json. The unreleased real-data path removes this fallback for new real workspaces; the guided demo continues to use it by explicit choice.
- The deployed home and Opportunities screens foreground three synthetic fixture roles. The unreleased real-data mode hides them; the guided demo keeps them labeled as samples.
- Real public job imports work only for supported pages; arbitrary job URLs are not reliably parsed. Imported requirements can need user review.
- Matching is reproducible but primarily deterministic token/skill matching. It is not yet a proven semantic recruiter-grade assessment.
- Model enrichment is optional and falls back to templates. Production model configuration and live quality/cost evaluation need verification before marketing the output as AI-generated.
- Email-draft and calendar-event actions are explicitly local mock records. There are no provider OAuth connections, external sends, calendar writes, or automatic job applications.
- Operations and evaluation screens measure this system and its fixture-based regression dataset; they do not prove real-world hiring outcomes.

## Next phases to become a real-data product

### Phase 1 — Real profile as the default (highest priority)

1. Implemented locally: new real-data workspaces have an empty profile and onboarding entry; demo fixtures require an explicit demo choice. Deploy and verify this on production after review.
2. Implemented locally: resume upload, field correction, editable job preferences, per-field source labels, and current-version confirmation. Resume-derived graduation year, experience, and skills link to stored evidence excerpts; those inferred values cannot retain deleted citations. Next: validate the profile experience with consented real user inputs and improve parsing beyond the current bounded heuristics.
3. Implemented locally: explicit start-fresh archives the synthetic profile and retains missions/documents; restore archives the current profile before reverting. Verify the existing-account experience in production after release.
4. Acceptance: a new production account starts with no Northstar candidate facts, completes onboarding with its own resume, and a mission cites only that account's reviewed evidence.

### Phase 2 — Real opportunities and trustworthy analysis

1. Implemented locally: sample jobs are hidden in real-data mode and retained for an explicitly selected guided demo and regression tests. Verify the production UI after release.
2. Implemented locally: a review checkpoint lets users remove unsupported extracted requirements, adjust importance, and exclude hard constraints, while retaining source snapshots and screenshot provenance. The UI shows source retrieval, posting, and expiry dates when supplied; expired postings are blocked from real-data missions. Repeat imports show whether their saved source snapshots differ by SHA-256. Explicitly labeled requirement lists in a JSON-LD description parse, and current Ashby postings use the public board API with exact URL matching. Live checks yielded five Lever and 12 Ashby source-backed requirements; a removed Ashby posting was rejected. Import errors identify missing pages, rendering failures, and absent structured postings. Next: improve other site formats across a broader representative sample.
3. Evaluate matching and eligibility against a consented set of real resumes and job postings. Add tests for unsupported claims, partial evidence, location/work authorization, stale postings, and source changes; publish measured results and limitations.
4. Acceptance: a user can import a supported live job, confirm its requirements, run a mission against their own profile, and trace each conclusion to a stored real source. No synthetic facts appear in that run.

### Phase 3 — Useful external actions, always user-controlled

1. Replace mock email/calendar records with provider integrations only after secure account linking, scoped OAuth consent, token storage/rotation, revocation, and per-provider error handling are implemented.
2. Preserve the existing approval checkpoint. Show the exact message or event before action, require a fresh explicit approval for each external side effect, and record provider receipts and idempotency keys.
3. Start with draft creation or calendar proposal; do not add automatic sending or job submission until the user experience, audit trail, and recovery behavior are validated.
4. Acceptance: an approved action affects the connected provider exactly once, a rejection has no provider effect, and the user can disconnect the account.

### Phase 4 — Public-product trust and operations

1. Implemented locally: authenticated JSON export of workspace data, including source snapshots and drafts, with workspace isolation and no credential fields. Implemented locally in the next-phase milestone: session/device management and authenticated password changes. Next: add email verification, password recovery, account/workspace deletion, and a privacy/retention policy suitable for resumes and job history. Verify the export on production after release.
2. Strengthen production protection: shared rate limiting at the edge, abuse controls for uploads/browser extraction, secret rotation, dependency scanning, and regular security review.
3. Exercise Aiven and Temporal backup restores, rollback after a failed migration, alerting, uptime/error monitoring, and capacity limits of the single VM. Keep current production data and volumes intact while testing recovery.
4. Validate the optional model path with real inputs, citation/unsupported-claim checks, latency and cost budgets, and safe fallback behavior before enabling it for general users.
5. Acceptance: real users can recover accounts, control their data, and rely on documented backup and incident procedures; the product can report measured reliability and quality.

## Immediate recruiter-demo path

The current guided demo is suitable for showing the engineering system now: create an isolated guest workspace, run a labeled sample mission, approve through the UI, and show Temporal progress, citations, drafts, and pipeline persistence. State that the inputs are synthetic and external actions are mocked. For a real-input recording after the next release, use a resume/project profile the owner is comfortable displaying and a supported public job posting, confirm the profile and job extraction, then verify the run does not cite seeded candidate facts. Production verification and measured quality with consented real inputs remain necessary before presenting this as finished product behavior.

## Inputs needed from the owner

- For a real-input demo: a resume or project evidence approved for public display, a stable public job posting, and permission to use both in a recording.
- For optional live model validation: chosen provider/model, API credentials stored outside Git, and an agreed spend limit.
- For real email/calendar actions later: selected providers and authorization to connect test accounts. These are not needed for the current recruiter demo.

Historical implementation details remain in Git history and architecture documentation. This file tracks the current state and next product milestones.
