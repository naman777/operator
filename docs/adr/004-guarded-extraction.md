# ADR 004: Guarded public-page extraction

Status: Accepted

## Context

Job pages are untrusted network content and can trigger SSRF, oversized responses, cross-origin requests, or prompt injection.

## Decision

Accept public HTTPS only, validate every resolved address, reject private networks, pin hosts, revalidate redirects, and bound time and bytes. Prefer JSON-LD; use restricted same-origin Playwright only as fallback. Treat retrieved text as data and give extraction models no tools.

## Consequences

Import fails closed. Some legitimate sites with authentication, unusual redirects, or complex browser dependencies remain unsupported.
