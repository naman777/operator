# ADR 003: Immutable evidence provenance

Status: Accepted

## Context

Application claims are useful only when reviewers can trace them to stored candidate and employer sources.

## Decision

Store bounded snapshots, checksums, exact excerpts, locations, retrieval times, and workspace ownership. Generate IDs locally. Profile corrections cannot rewrite source evidence, and artifact edits create immutable revisions.

## Consequences

Claims remain auditable and revisions comparable. Storage grows, and evidence deletion must update relational and vector records atomically.
