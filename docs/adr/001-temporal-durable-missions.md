# ADR 001: Temporal for durable missions

Status: Accepted

## Context

Opportunity analysis crosses browser retrieval, matching, verification, human approval, and artifact generation. These operations can fail or wait beyond one HTTP request, and retries must not duplicate effects.

## Decision

Use Temporal for workflow history, retries, approval signals, and restart recovery. Keep product state and activity outputs in PostgreSQL. Dispatch through a database outbox with stable workflow IDs and terminal dead-letter handling.

## Consequences

Restarts resume from checkpoints and duplicate dispatch is safe. Temporal is another stateful dependency whose history requires separate persistence and recovery.
