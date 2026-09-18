# Initial threat model

Implemented: cryptographically random guest credentials, hashed credentials at rest, workspace-scoped reads/writes, strict input schemas, transactional audit event, idempotency uniqueness, and no external network tools. Job URLs are saved as data only, never fetched by this increment. Request logs exclude bearer credentials and bodies.

Before any public deployment: account session management, Auth.js integration, request/mission rate limits, retention/reset, HTTPS, CSP, explicit CORS policy if origins split, and dependency scanning.

Before extraction: reject credentials and non-HTTP protocols in URLs, resolve and deny private/link-local IPs at every redirect and browser subrequest, protect against DNS rebinding, cap bytes/time, and isolate the browser network. Pydantic HttpUrl validation alone is not an SSRF defense.

Before model tools: preserve source boundaries, treat retrieved text as untrusted, never put integration secrets in prompts, allowlist tools, verify every positive match against evidence, and enforce cost/token/call limits.

Before side effects: bind approval to exact versioned payload and workspace, enforce expiry, apply idempotency, audit changes, and reject stale approvals.


Current artifact controls: drafts use completed verified checkpoints, stored evidence citations, transaction-scoped creation, and a unique mission/type/version index. No external submission is implemented. Durable approval enforcement remains required before external connectors.
