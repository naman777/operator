# ADR 005: Workspace isolation and approval boundaries

Status: Accepted

## Context

The guest demo must prevent visitors from reading each other's data, while proposed external effects require explicit human control.

## Decision

Issue random guest tokens, store only hashes, expire them after 24 hours, and scope every query and mutation to the workspace. Keep secrets outside tool schemas. Require durable approval, revalidate edited payloads, and key side effects by unique approval IDs.

## Consequences

The demo needs no account provider and cross-workspace access fails closed. Long-lived public accounts will later map authenticated identities onto the same workspace boundary.
