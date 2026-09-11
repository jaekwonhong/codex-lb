# Durable, explicit member-switch commands

## Why

The manual UI candidate removed lifecycle-driven mutations, but browser storage
still owns progression and the auth status GET still advances OAuth. A browser
restart or lost reply cannot be resolved from durable server evidence.

## What Changes

- Make auth status GET a stored snapshot; use an explicit write-authorized POST
  for OAuth advancement.
- Introduce a durable server-owned run and command admission record in the
  existing application database. Preserve intent before effects and use revision
  compare-and-swap; no lease expiration authorizes a second execution.
- Make the manual UI keep only a run locator. Small phases and available actions
  come from the server; detailed diagnostics are not transition authority.
- Persist Companion client-flow receipts and split membership decisions from
  browser execution and operation storage without rewriting browser mechanics.
- Review automation only after failure-boundary tests; do not attach automatic
  mutation to browser lifecycle or enable an unqualified scheduler.

## Impact

Member auth and new member-switch APIs, frontend manual panel, Companion protocol,
database schema, offline tests and release compatibility. Requires coordinated
server/Companion/frontend rollout; no rollout is performed in this change.
