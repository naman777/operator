# Synthetic workflow walkthrough

1. Open http://127.0.0.1:3000 and enter a guest workspace.
2. Choose Northstar and save a mission.
3. Choose "Exhaust retries, then retry manually", then start the sample run.
4. Inspect real step events and the failed matching step; retry from its checkpoint.
5. Confirm earlier steps retain their attempt counts and the final report has a score with evidence links.
6. Inspect eligibility: unspecified hard requirements are unknown, even with a high skill score.
7. Open each of the four draft artifacts and expand its source citations. Check that candidate statements match stored project excerpts.
8. Open Application Pipeline to see the saved role; reload to confirm persistence.

This demonstrates real Temporal execution over synthetic fixtures. It does not fetch a public job page, call a model, send an application, or wait on a durable approval gate. Evaluation Lab has no measured model results yet.
