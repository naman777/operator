# Deployment runbook

This runbook describes the production-shaped Compose configuration. It does not make the current guest-only build safe for unrestricted public traffic. Put authentication, rate limiting, TLS, and network controls in front of it before exposing it beyond a controlled demo.

## Required platform services

- A PostgreSQL 16 database with the `vector` extension, automated backups, point-in-time recovery, and TLS required.
- A persistent Temporal service reachable by both the API and worker.
- A TLS reverse proxy or load balancer. Only the web container should be reachable through it.
- A container registry containing immutable API and web image tags.
- A secret manager for `DATABASE_URL`, model credentials, and future provider credentials.

Redis and MinIO are omitted from `compose.production.yaml` because the application does not use them yet.

## Build and publish

Use the commit SHA as the immutable tag:

```sh
docker build -f apps/api/Dockerfile -t REGISTRY/operator-api:GIT_SHA .
docker build -f apps/web/Dockerfile -t REGISTRY/operator-web:GIT_SHA .
docker push REGISTRY/operator-api:GIT_SHA
docker push REGISTRY/operator-web:GIT_SHA
```

Copy `.env.production.example` outside the repository, replace every placeholder, and load the values through the deployment platform. Do not commit the populated file.

Validate resolved configuration before rollout:

```sh
docker compose --env-file /secure/path/operator.env -f compose.production.yaml config --quiet
```

## Rollout

1. Confirm the latest database backup and restore test.
2. Pull the immutable images.
3. Run the one-shot `migrate` service. The PostgreSQL advisory lock prevents concurrent migration runners.
4. Start the API and wait for `/health/ready` to pass.
5. Start the worker, then the web service.
6. Verify `/health/live`, `/health/ready`, guest-session creation, one synthetic mission, SSE replay, and the application pipeline.
7. Route a small portion of traffic to the new web service before completing the rollout.

With Compose, steps 3–5 are encoded as dependency conditions:

```sh
docker compose --env-file /secure/path/operator.env -f compose.production.yaml up -d
docker compose --env-file /secure/path/operator.env -f compose.production.yaml ps
```

`/health/live` proves that the API process can serve requests. `/health/ready` also checks database connectivity and is the endpoint used by the service health check.

## Rollback

Application rollback uses the preceding immutable API and web tags. Do not automatically reverse schema migrations: current migrations are forward-only and may have written data in the new shape.

1. Stop incoming traffic to the failing release.
2. Restore the previous image tags and restart API, worker, and web.
3. Confirm both health endpoints and run the synthetic smoke workflow.
4. If a migration caused data loss or incompatible writes, stop all writers and restore the database to a separate instance from the pre-deploy backup. Validate it before changing the production connection string.

## Backups and recovery

- Enable managed PostgreSQL point-in-time recovery and daily snapshots.
- Retain at least one backup from before every schema migration.
- Perform a restore drill into an isolated database before the first public release and at a regular interval afterward.
- Temporal persistence requires its own managed backup policy. Product records alone cannot reconstruct in-flight workflow histories.
- Record recovery-point and recovery-time results after each drill.

## Provider outages

- Model enrichment already falls back to deterministic parsing, matching, and templates. Keep `OPERATOR_MODEL_ENABLED=0` when credentials, pricing, or provider health are uncertain.
- A Temporal outage prevents new workflow progress but leaves accepted dispatch commands and stored checkpoints intact. Restore Temporal before replaying queued work.
- A database outage makes `/health/ready` fail, removing API and worker instances from service. `/health/live` remains available for process diagnosis.
- Real email and calendar providers are not connected; existing connector actions remain local mock records.

## Alerts to configure

- API readiness failures and elevated 5xx rate.
- Worker absence or a growing Temporal task-queue backlog.
- Migration job failure.
- PostgreSQL storage, connection saturation, replication lag, and backup failure.
- Mission failure rate, model cost, approval age, and P95 workflow latency.
- TLS certificate expiry and reverse-proxy error rate.

Public deployment remains blocked on production authentication, API rate limiting, real secret management, restore verification, and end-to-end staging validation.
