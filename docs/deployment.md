# Production deployment runbook

Operator's direct-production target is Google Compute Engine. The application database is Aiven PostgreSQL with pgvector and TLS. Temporal uses a separate PostgreSQL 16 container and persistent Docker volume on the VM. Caddy is the only service that publishes host ports.

## Production topology

compose.gcp-production.yaml runs these services:

- temporal-postgres: private PostgreSQL used only for Temporal history and visibility.
- temporal-schema: one-shot Temporal schema initializer and upgrader.
- temporal: the production Temporal server image with PostgreSQL persistence.
- temporal-namespace: idempotent namespace creation.
- migrate: one-shot application migrations against Aiven.
- api, workflow-worker, and web: immutable Operator images from GHCR.
- caddy: automatic HTTPS and reverse proxy to the web service.

The backend bridge contains the API, worker, web, Temporal, and Temporal PostgreSQL. The edge bridge contains only Caddy and web. Only TCP 80, TCP 443, and UDP 443 are published. PostgreSQL 5432, Temporal 7233, API 8000, and web 3000 are not mapped to the host.

The single VM remains one failure domain. The Temporal PostgreSQL and Caddy state survive container replacement through named volumes, but they do not survive loss of the VM disk. Schedule Google persistent-disk snapshots or copy encrypted Temporal dumps off the VM after the first deployment.

## Server environment

Keep /opt/operator/.env.production on the VM with mode 600. Do not commit or print it. .env.gcp-production.example documents the variable names.

Required values:

- OPERATOR_DOMAIN: DNS name whose A/AAAA record points to the VM.
- DATABASE_URL: Aiven SQLAlchemy URL containing sslmode=require.
- TEMPORAL_POSTGRES_PASSWORD: a long random password used only by the local Temporal database.
- OPERATOR_API_IMAGE and OPERATOR_WEB_IMAGE: defaults for manual operation; CI supplies immutable SHA tags for each rollout.

The Aiven application database and Temporal persistence databases are separate. Do not reuse the Aiven database URL for Temporal.

Before deployment, confirm Aiven backups are enabled and the Aiven user can create tables, indexes, and the vector extension required by migrations. The rollout script runs migrations before starting the API and stops on any migration failure.

## Read-only preflight

On the VM, inspect without displaying environment values:

    hostname
    cat /etc/os-release
    nproc
    free -h
    df -h / /opt
    docker version
    docker compose version
    stat -c '%a %U %G %n' /opt/operator/.env.production
    docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
    docker volume ls
    ss -lnt

Check required variable names without printing their values:

    for key in OPERATOR_DOMAIN DATABASE_URL TEMPORAL_POSTGRES_PASSWORD; do
      grep -q "^$key=." /opt/operator/.env.production &&
        echo "$key present" || echo "$key missing"
    done

## Manual rollout

The script validates Compose and the Aiven TLS setting, pulls images, backs up a running Temporal database, initializes or upgrades Temporal schemas, verifies Temporal, runs application migrations, and starts API, worker, and web behind health gates.

Run without public exposure first:

    cd /opt/operator
    sh scripts/deploy-gcp.sh

After internal services are healthy and public exposure is approved:

    cd /opt/operator
    sh scripts/deploy-gcp.sh --expose

The second command starts Caddy on 80/443. DNS must already point to the VM and Google Cloud firewall rules must permit inbound TCP 80/443 for certificate issuance and HTTPS. Firewall or DNS changes are separate infrastructure actions and require explicit approval.

Public checks:

    curl --fail --silent --show-error https://YOUR_DOMAIN/
    curl --fail --silent --show-error https://YOUR_DOMAIN/api/health/live
    curl --fail --silent --show-error https://YOUR_DOMAIN/api/health/ready

## GitHub Actions

.github/workflows/ci.yml runs tests, publishes SHA-tagged API and web images to GHCR, copies only non-secret deployment files, and runs the same staged deployment script over SSH.

Repository variables:

| Name | Value |
| --- | --- |
| PRODUCTION_ENABLED | true only after VM preflight and deployment approval |
| PRODUCTION_PUBLIC_ENABLED | true only after approval to start Caddy publicly |
| PRODUCTION_HOST | 34.180.44.15 |
| PRODUCTION_USER | nkundra_be23 |
| PRODUCTION_PATH | /opt/operator |
| PRODUCTION_URL | https://YOUR_DOMAIN |

GitHub production environment secrets:

| Name | Purpose |
| --- | --- |
| PRODUCTION_SSH_KEY | Private key authorized for the deployment user |
| PRODUCTION_KNOWN_HOSTS | Independently verified pinned host-key line |

The workflow uses its short-lived GitHub token to pull this repository's GHCR packages and logs out after deployment. The server-resident .env.production file is never copied, printed, or committed. Add a required reviewer to the GitHub production environment if you want each rollout to pause for manual approval.

## Rollback and recovery

Rollback changes only the API and web image tags to a prior commit SHA, then reruns scripts/deploy-gcp.sh. Application migrations are forward-only and must not be automatically reversed.

Before each later deployment, the script creates a compressed pg_dumpall of Temporal PostgreSQL under /opt/operator/backups when that service is already running. Aiven owns application-database backups; confirm its backup and restore policy independently. Never remove Docker volumes during rollback.

If a rollout fails before Caddy starts, public traffic remains unchanged. If it fails after an existing Caddy is already serving, restore the previous image tags and rerun the deployment script. Inspect status with:

    docker compose --env-file /opt/operator/.env.production -f /opt/operator/compose.gcp-production.yaml ps
