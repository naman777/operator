# Account session controls

Authenticated users can manage sign-ins from Account security in Mission Control.
Each session has a 30-day absolute expiry. The displayed browser label comes from
the sign-in User-Agent header (bounded to 512 characters); it is not proof of a
device's identity. Older sessions display Unknown browser.

- `GET /v1/accounts/sessions` lists active sessions for the signed-in account,
  including which is current. Responses are private and no-store.
- `DELETE /v1/accounts/sessions/{id}` revokes a session. Repeating a revocation
  is harmless; another account's ID returns 404.
- `POST /v1/accounts/sessions/revoke-others` keeps the current session and revokes
  other sessions belonging to this account.
- `POST /v1/accounts/password` accepts `current_password` and `new_password`,
  verifies the old password, stores the new password hash, and revokes all sessions
  in the same transaction. The UI clears local credentials and requires sign-in.

Revocation prevents subsequent authenticated requests. It does not undo completed
requests, cancel running missions, or disconnect a stream already authorized.
Password change is not forgotten-password recovery. Email verification and recovery
remain unimplemented. Guest credentials cannot manage account sessions, and claimed
workspaces cannot issue or authenticate guest credentials.

## Release checks

Apply migration 019 along with the existing unreleased migrations before starting
the new API. It adds an optional label column and is repeatable. No session token
is exposed in listings or exported data. Verify with two browser sessions that
revocation and password change reject the old credentials. Production has not been
changed by this milestone.

## Dependency monitoring

`.github/workflows/security.yml` runs independent Python and JavaScript audits on
pull requests, main pushes, a weekly schedule, and manual dispatch. The main quality workflow calls both audits, and image publication requires
quality checks and security audits to pass. Weekly and manual audit runs remain
available independently. Audit failures and service outages fail
the relevant check; no advisories are ignored. Review failing logs, update the
smallest affected dependency set, and rerun tests/builds before release. Successful
audits establish only that the advisory services found no known vulnerabilities
at that moment; they do not replace security review.

Python audit command reference: https://github.com/pypa/pip-audit

## Shared admission controls

Migration 020 adds atomic fixed-window request counters in the application database.
All API instances using that database share limits, which survive process restarts.
The API stores hashes rather than raw client addresses or tokens, but an address
hash should not be treated as anonymous. Expired buckets are removed in batches
of up to 100 per check. Low-traffic expired rows can remain until further requests.
Fixed windows allow a burst across a window boundary.

The existing general, authentication, and mission quotas still apply. New
`OPERATOR_UPLOADS_PER_HOUR` (default 30) and `OPERATOR_IMPORTS_PER_HOUR` (default 20)
limits apply by client network before parsing or extraction. In production Caddy
and the private web proxy establish forwarding headers; the API remains private.
Do not expose a Uvicorn listener that trusts all forwarded headers to the internet.
A shared-database admission failure returns 503 rather than bypassing quotas.
Database health probes remain available. These controls are not an edge WAF.
