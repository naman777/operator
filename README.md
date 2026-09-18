# Operator

A personal work execution agent, starting with evidence-backed opportunity analysis.

**Current build: durable synthetic opportunity workflow.** Open a guest workspace, select a sample job, run an analysis, inspect live events and evidence, simulate failures, retry from checkpoints, and review four cited application drafts. Completed sample runs update the local application pipeline.

The current matcher and drafts are deterministic templates using synthetic fixtures. Public-page extraction, profile ingestion, embeddings, LLM matching, durable approval signals, and measured model evaluations remain pending. The approval inbox can list/resolve stored approvals, but it does not yet gate workflow execution. See [PROGRESS.md](PROGRESS.md).

## Local setup

Prerequisites: Python 3.12, Node.js 22+, pnpm 10.30.3. Run commands from the repository root, using the same virtual environment and database for API and worker.

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pnpm install
pnpm contracts
python scripts/migrate.py
```

Run these in four terminals:

```sh
# 1. Official Temporal dev server; no Docker required.
python scripts/temporal_dev.py

# 2. Product API
python -m uvicorn operator_api.main:app --reload --host 127.0.0.1 --port 8000

# 3. Workflow worker and durable dispatcher
python -m operator_worker.main

# 4. Dashboard
pnpm dev
```

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8000/docs. Temporal UI: http://127.0.0.1:8233.

The Temporal SDK downloads its official dev-server executable on first use. Its history is stored under ignored `.local/temporal`; product data is stored in ignored `operator.db`. Set `DATABASE_URL` consistently for API, migrations, and worker to use another database. Set `TEMPORAL_ADDRESS` for another Temporal server. Existing checkouts must run migrations before restarting services.

### Docker

```sh
docker compose up --build
```

Compose defines web, API, workflow worker, PostgreSQL/pgvector, Redis, Temporal, and MinIO. The worker waits for the migrated API to become healthy. Redis fan-out and object storage are not wired yet. Langfuse is not included. Container configuration validates, but full Docker/PostgreSQL runtime verification remains pending. Local credentials and loopback ports are for development only.

## Demo

1. Open a guest workspace and choose Northstar.
2. Save the mission, then start the sample run.
3. Optionally select an exhausted failure before starting; watch the failed matching step, then retry it.
4. Inspect step outputs, evidence matches, and eligibility explanations. Missing constraints stay unknown.
5. Review the cover letter, resume suggestions, recruiter message, and interview brief, including their citations.
6. Open Application Pipeline. The role is saved locally; nothing has been submitted.

Drafts have immutable version-1 records and require review. Editing, later versions, and diffs are not implemented yet.

## Validation

```sh
python -m pytest -q
python -m ruff check apps/api services scripts tests infra/migrations
pnpm contracts
pnpm format:check
pnpm test:web
pnpm typecheck
pnpm build
```

For live Temporal integration, set `OPERATOR_RUN_TEMPORAL_TESTS=1`, then run `python -m pytest tests/workflow/test_temporal.py -q`. Without `TEMPORAL_ADDRESS`, the test starts and stops its own isolated server. Test task queues are unique, so they do not consume development missions.

With all four services running, execute `python scripts/smoke_workflow.py` to test the complete HTTP path through the dashboard proxy. It creates an isolated synthetic guest workspace and checks failure recovery, SSE replay, artifacts, and pipeline data. This is not a visual browser test.

## Modules

- `apps/web`: Next.js dashboard, live inspector, pipeline, approval inbox, and artifact viewer.
- `apps/api`: contracts, workspace authorization, persistence, streaming, and artifact generation.
- `services/workflow-worker`: Temporal workflow, dispatch, activities, fixture matching, and eligibility.
- `packages/contracts`: generated JSON Schema, OpenAPI, and TypeScript declarations.
- `data/demo`: synthetic candidate and three job snapshots.
- `infra/migrations`: versioned schema upgrades.
- `tests`: authorization, idempotency, migrations, provenance, and live workflow recovery.
- `docs`: architecture, threat model, and demo instructions.

No model keys are needed. Arbitrary job URLs can be saved but cannot execute yet. No external actions are performed. Public deployment requires additional authentication, rate limits, durable approval enforcement, and the remaining security work in the plan.
