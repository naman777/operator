# Deployment runbook

This runbook describes the production-shaped Compose configuration. It does not make the current guest-only build safe for unrestricted public traffic. Put authentication, shared edge rate limiting, TLS, and network controls in front of it before exposing it beyond a controlled demo. The built-in limiter protects one API process and intentionally does not claim multi-replica coordination.

## Recommended personal-project production

For this project, the most direct deployment is `compose.single-host.yaml` on one EC2 instance. It runs Caddy, the web app, API, worker, PostgreSQL/pgvector, and a persistent single-node Temporal dev server. Caddy is the only public service and obtains HTTPS certificates automatically.

This avoids separate database and Temporal accounts. It is a sensible portfolio deployment with a single failure domain. Use EBS snapshots and the pipeline's pre-deploy PostgreSQL dumps. A future high-availability version should move PostgreSQL and Temporal to managed services and use `compose.production.yaml`.

Recommended host shape:

- Ubuntu 24.04 LTS on x86-64.
- At least 4 vCPU, 16 GB RAM, and 80 GB gp3 storage because Chromium, Temporal, PostgreSQL, the API, and Next.js share the machine.
- An Elastic IP.
- Security-group ingress for TCP 80/443 from the internet and TCP 22 only from the administrator's IP. Do not expose PostgreSQL, Temporal, API, or web container ports.
- Docker Engine with the Compose plugin and a non-root deployment user permitted to run Docker.

Point an `A`/`AAAA` record for the chosen domain to the instance before starting Caddy. Copy `.env.single-host.example` to `/opt/operator/.env.production`, replace all placeholders, set file mode `600`, and authenticate Docker to GHCR with a read-only package token if the package is private.

The single-node Temporal service uses a persistent SQLite history file. It survives container restarts but is not a highly available production Temporal cluster. This limitation is acceptable for the personal demo target and must remain visible in project documentation.

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

## GitHub Actions CI/CD

`.github/workflows/ci.yml` performs the following:

1. Runs the complete quality suite for every push and pull request.
2. After a successful `main` push or manual dispatch, builds the API and web containers and publishes immutable commit-SHA tags to GHCR.
3. If the repository variable `PRODUCTION_ENABLED` is `true`, deploys those exact images to the GitHub `production` environment over SSH.
4. Copies only non-secret manifests, takes a compressed PostgreSQL dump when a database is already running, runs migrations, waits for container health checks, and verifies the public HTTPS URL.

Configure one repository variable:

- `PRODUCTION_ENABLED=true` after the server is fully prepared. Leave it unset while testing image publication.

Configure the GitHub `production` environment with optional reviewer approval and these values:

| Type | Name | Value |
| --- | --- | --- |
| Variable | `PRODUCTION_HOST` | EC2 Elastic IP or SSH hostname |
| Variable | `PRODUCTION_USER` | Restricted deployment user, usually `ubuntu` |
| Variable | `PRODUCTION_PATH` | `/opt/operator` |
| Variable | `PRODUCTION_URL` | `https://your-domain.example` |
| Secret | `PRODUCTION_SSH_KEY` | Private deployment key |
| Secret | `PRODUCTION_KNOWN_HOSTS` | Pinned host-key line from `ssh-keyscan`, verified independently |

The server keeps the secret `.env.production` file. GitHub Actions never creates or reads it. The deployment user and GHCR credential should have only the permissions needed to pull images and operate this Compose project.

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
- Dispatch commands retry with bounded exponential backoff. After `OPERATOR_DISPATCH_MAX_ATTEMPTS`, the command is dead-lettered once, its sanitized error category is recorded as a mission event, and an exhausted start marks the mission failed for explicit operator review.
- Real email and calendar providers are not connected; existing connector actions remain local mock records.

## Alerts to configure

- API readiness failures and elevated 5xx rate.
- Worker absence or a growing Temporal task-queue backlog.
- Migration job failure.
- PostgreSQL storage, connection saturation, replication lag, and backup failure.
- Mission failure rate, model cost, approval age, and P95 workflow latency.
- TLS certificate expiry and reverse-proxy error rate.

Public deployment remains blocked on production authentication, shared multi-replica rate limiting, real secret management, restore verification, and end-to-end staging validation.
