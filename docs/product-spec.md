# First-sprint product specification

## User stories
1. As a recruiter, I can enter an isolated guest workspace without connecting a private account.
2. As a candidate, I can choose a synthetic job or save a public job URL as a mission with a bounded budget.
3. As a reviewer, I can reload a mission and inspect its recorded creation event without seeing another workspace's data.

## Screens
- Mission Control: mission totals, new-mission form, sample selectors, persistent mission list.
- New Mission: URL, goal, fixed initial $1 budget cap, save action.
- Run Inspector: mission status, pending step map, recorded events, budget and usage empty states.
- Opportunity Detail: sample cards with requirements and source excerpts; application history is pending.
- Approval Inbox: durable Temporal wait with approve/reject controls and a 24-hour expiry.
- Evaluation Lab: persisted deterministic 40-case runs with accuracy, eligibility, citation, unsupported-claim, score-error, and P50/P95 matcher-latency metrics.
- Operations: workspace-scoped mission outcomes, cost per completed mission, step and tool success, latency percentiles, and eight-week mission cohorts from persisted records.

## Contracts and state
Pydantic models are authoritative. `pnpm contracts` exports JSON Schema v1 and OpenAPI, then generates TypeScript declarations. Clients may not supply workspace IDs or mission status.

Implemented sample states: draft -> queued -> planning -> extracting -> matching -> verifying -> awaiting approval -> generating -> completed. Activities persist outputs and events; failure becomes failed after bounded retries, manual retry preserves completed checkpoints, and cancellation rejects late writes. Current generation creates cited, revisioned draft artifacts and a local saved pipeline entry after approval. Email-draft and calendar proposals can be edited before approval and materialize only as local mock actions.

## Fit rubric v1 (deterministic fixture implementation)
Required requirements weigh 2; preferred requirements weigh 1. Supported evidence contributes 1, partial contributes 0.5, missing contributes 0. Score = 100 * sum(weight * contribution) / sum(weights). A zero-requirement posting scores 0 with unknown eligibility, never 100%. Hard eligibility is evaluated separately with eligible/ineligible/unknown states; unknown constraints cannot silently pass. A positive match must reference stored candidate evidence. The current matcher uses exact skills in stored evidence. Structured semantic matching is pending; weighting and eligibility remain deterministic.

## Non-goals for this increment
Public JSON-LD job pages are fetched through guarded HTTPS transport, with a same-origin Playwright fallback for JavaScript rendering and an authenticated screenshot preview. There are no model calls, email sends, automatic applications, or real account sessions. Temporal workflow durability is tested with worker restarts. Public deployment requires rate limits, account auth, broader browser compatibility testing, and the remaining security milestones.
