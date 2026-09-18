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
- Approval Inbox: honest empty state until durable approvals are implemented.
- Evaluation Lab: no fabricated results; awaiting evaluation execution.

## Contracts and state
Pydantic models are authoritative. `pnpm contracts` exports JSON Schema v1 and OpenAPI, then generates TypeScript declarations. Clients may not supply workspace IDs or mission status.

Implemented state: draft. Planned execution: planning -> extracting -> researching -> matching -> verifying -> awaiting_approval -> generating -> updating_pipeline -> completed. Rejection/cancellation -> cancelled; activity failure -> failed; retry resumes the failed checkpoint. Drafts do not auto-run.

## Fit rubric v1 (specified, not yet executed)
Required requirements weigh 2; preferred requirements weigh 1. Supported evidence contributes 1, partial contributes 0.5, missing contributes 0. Score = 100 * sum(weight * contribution) / sum(weights). A zero-requirement posting has unknown fit, not 100%. Hard eligibility is evaluated separately with eligible/ineligible/unknown states; unknown constraints cannot silently pass. A positive match must reference stored candidate evidence. Semantic matching uses a model; weighting and eligibility use deterministic code.

## Non-goals for this increment
No URL fetching, model calls, email sending, automatic applications, real accounts, or claims of workflow durability. Public deployment requires rate limits, expiring sessions, proper account auth, and the remaining hardening milestones.
