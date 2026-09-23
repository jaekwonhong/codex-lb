# Optional five-hour OFF production release

## Why
The exact optional-five-hour P2 source and b98 image are approved only as an isolated OFF candidate. Fresh read-only production admission passed, but current-data PostgreSQL and manifest-bound first-start/recovery qualification remain required.

## What Changes
- Qualify the unchanged b98 image on a verified fresh isolated PostgreSQL copy, including synthetic legacy/v2 repository recovery because production retained history is empty.
- Add operation-owned manifest-bound image admission and first-start gating without fabricating an owning Git commit or changing frozen product files.
- Qualify the exact host replacement/recovery transaction before using it to replace only Beta, remaining OFF.
- Retain the immediate predecessor and its sentinel; require stopped/restart=no/disconnected predecessor state after successful cutover, and restore exact configured networks when rollback is needed.

## Impact
Operations artifacts and evidence only. No product source, schema, Stable, Companion, production PostgreSQL replacement, activation, live canary, reset, remove, invite, commit, or merge.
