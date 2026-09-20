# ADR 002: Deterministic decisions with guarded model enrichment

Status: Accepted

## Context

Models improve sparse extraction and prose, but eligibility and fit decisions must remain reproducible and source-backed without provider access.

## Decision

Keep eligibility, evidence mappings, scores, and match statuses deterministic. Explicitly enabled model calls may extract cited requirements, review explanations, and draft prose. Reject unknown IDs, unsupported numeric claims, and missing citations, then use the deterministic fallback.

## Consequences

Core missions run without keys and evaluations remain stable. Model output cannot silently change authoritative decisions, at the cost of less agent flexibility.
