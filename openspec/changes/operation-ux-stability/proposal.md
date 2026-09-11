# Operation UX stability

## Why

Several management surfaces close destructive confirmation dialogs even when the
server rejects the request, and some immediate mutations leave rejected promises
unhandled. Filtered sticky-session deletion can also execute against a newer filter
than the one the operator confirmed.

## What Changes

- Keep destructive confirmations open until the exact request succeeds.
- Preserve the exact target or filter snapshot that the operator confirmed.
- Show mutation failure and no-auto-retry guidance inside retained dialogs.
- Consume rejected mutation promises after existing React Query error handling.
- Do not add retries, optimistic writes, backend changes, or new destructive APIs.
