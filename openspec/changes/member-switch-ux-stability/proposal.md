# Manual member-switch UX and request lifecycle

## Why
Initial restoration runs independently of explicit refresh and commands. Late replies
can replace newer state, including after an access change. Failed explicit refresh
also leaves previously checked state actionable, and a missing locator is handled
differently on mount and refresh. These are current UX/stability defects, not reasons
to add automatic mutation or recovery.

## What Changes
- Give asynchronous UI requests one owner; cancel/discard superseded restoration and
  requests from an old mount or permission lifecycle.
- Use the same stored-state recovery path on mount and explicit refresh; only a
  confirmed `run_not_found` can discard its exact browser locator.
- Keep commands unavailable after failed refresh until a successful stored read.
- Explain common operator next steps without inventing automatic retries or releases.

## Impact
Member-switch frontend and regression tests. No API/schema, Companion, authentication,
membership, automated worker or durable backend policy change. Deploy only a matched
beta image with the new static files; preserve current backend and Companion identities.
