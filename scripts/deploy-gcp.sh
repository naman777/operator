#!/bin/sh
set -eu

project_dir="${OPERATOR_DEPLOY_PATH:-/opt/operator}"
env_file="${OPERATOR_ENV_FILE:-$project_dir/.env.production}"
compose_file="$project_dir/compose.gcp-production.yaml"
expose=false

if [ "${1:-}" = "--expose" ]; then
  expose=true
elif [ -n "${1:-}" ]; then
  echo "usage: $0 [--expose]" >&2
  exit 2
fi

cd "$project_dir"

if [ ! -f "$env_file" ]; then
  echo "Missing production environment file: $env_file" >&2
  exit 1
fi

for key in OPERATOR_DOMAIN DATABASE_URL TEMPORAL_POSTGRES_PASSWORD; do
  if ! grep -q "^$key=." "$env_file"; then
    echo "Missing required variable in .env.production: $key" >&2
    exit 1
  fi
done

if ! grep -Eq '^DATABASE_URL=.*([?&]sslmode=require|[?&]ssl=require)' "$env_file"; then
  echo "DATABASE_URL must require TLS with sslmode=require" >&2
  exit 1
fi

compose() {
  docker compose --env-file "$env_file" -f "$compose_file" "$@"
}

wait_healthy() {
  service="$1"
  attempts="${2:-36}"
  count=0

  while [ "$count" -lt "$attempts" ]; do
    container_id="$(compose ps -q "$service")"
    if [ -n "$container_id" ]; then
      state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
      if [ "$state" = healthy ] || [ "$state" = running ]; then
        return 0
      fi
      if [ "$state" = unhealthy ] || [ "$state" = exited ] || [ "$state" = dead ]; then
        echo "$service entered state: $state" >&2
        compose logs --tail 80 "$service" >&2
        return 1
      fi
    fi
    count=$((count + 1))
    sleep 5
  done

  echo "$service did not become healthy in time" >&2
  compose logs --tail 80 "$service" >&2
  return 1
}

mkdir -p "$project_dir/backups"
compose config --quiet
compose pull

postgres_id="$(compose ps -q temporal-postgres)"
if [ -n "$postgres_id" ] && [ "$(docker inspect --format '{{.State.Running}}' "$postgres_id")" = true ]; then
  backup="$project_dir/backups/temporal-predeploy-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
  compose exec -T temporal-postgres sh -c 'pg_dumpall -U "$POSTGRES_USER"' | gzip > "$backup"
  chmod 600 "$backup"
  echo "Created Temporal PostgreSQL backup: $backup"
fi

compose up -d --no-deps temporal-postgres
wait_healthy temporal-postgres

compose run --rm --no-deps temporal-schema
compose up -d --no-deps temporal
wait_healthy temporal

compose run --rm --no-deps temporal-namespace
compose run --rm --no-deps migrate

compose up -d --no-deps api
wait_healthy api

compose up -d --no-deps workflow-worker web
wait_healthy workflow-worker
wait_healthy web

if [ "$expose" = true ]; then
  compose up -d --no-deps caddy
  wait_healthy caddy
else
  echo "Application services are healthy. Caddy was not started; run again with --expose after approval."
fi

compose ps
