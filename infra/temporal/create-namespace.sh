#!/bin/sh
set -eu

: "${TEMPORAL_ADDRESS:?TEMPORAL_ADDRESS is required}"

namespace="${TEMPORAL_NAMESPACE:-default}"
retention="${TEMPORAL_NAMESPACE_RETENTION:-7d}"

if ! temporal operator namespace describe --address "${TEMPORAL_ADDRESS}" --namespace "${namespace}" >/dev/null 2>&1; then
  temporal operator namespace create \
    --address "${TEMPORAL_ADDRESS}" \
    --namespace "${namespace}" \
    --retention "${retention}"
fi

attempt=0
while [ "$attempt" -lt 30 ]; do
  if temporal operator namespace describe --address "${TEMPORAL_ADDRESS}" --namespace "${namespace}" >/dev/null 2>&1; then
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done

echo "Temporal namespace did not become readable in time" >&2
exit 1
