# Operator

A personal work execution agent, starting with evidence-backed opportunity analysis.

**Current build: first-sprint foundation.** You can open an isolated guest workspace, inspect synthetic jobs and candidate evidence, save persistent draft missions, and inspect their recorded creation events. Workflow execution, model analysis, approvals, and evaluation results are not yet implemented. See [PROGRESS.md](PROGRESS.md) for the live checklist.

## Local startup

Prerequisites: Python 3.12+, Node.js 22+, pnpm 10.30.3.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pnpm install
pnpm contracts
python -m uvicorn operator_api.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, run `pnpm dev`, then open http://localhost:3000. The API defaults to a persistent `operator.db` SQLite file in the working directory. API documentation: http://localhost:8000/docs.

### Docker

```sh
docker compose up --build
```

The local stack defines web, API, PostgreSQL/pgvector, Redis, Temporal dev server, and MinIO. The API applies migrations on startup. Credentials are local development defaults, ports bind to loopback, and this configuration is not production-ready. Docker runtime verification status is recorded in PROGRESS.md. Langfuse is not included yet.

## Checks

```sh
python -m pytest -q
python -m ruff check apps/api scripts tests
pnpm contracts
pnpm typecheck
pnpm build
```

Schemas live in `apps/api/operator_api/schemas.py`; generated OpenAPI and TypeScript are in `packages/contracts`. Run `pnpm contracts` after contract changes. CI checks for generated-contract drift.

## Layout

- `apps/web`: Next.js 15 dashboard and same-origin API proxy.
- `apps/api`: FastAPI, Pydantic contracts, authorization, SQLAlchemy persistence.
- `data/demo`: one synthetic candidate, three jobs, and HTML snapshots.
- `infra/migrations`: initial relational migration.
- `tests/integration`: persistence, isolation, validation, and concurrent idempotency checks.
- `docs`: product specification, architecture, threat model, demo script.

No model API keys are needed for this increment. A pasted URL is stored, not fetched. No external actions are performed.
