# Pre-membership failure closeout

## Why

A retained manual member-switch operation can fail before any membership mutation begins, but the
backend currently keeps the global scope indefinitely because failed operations with an operation ID
cannot be explicitly finalized.

## What Changes

- Parse the Companion operation trace and invitation-settlement evidence.
- Permit explicit `finish` only when durable evidence proves membership mutation never started.
- Keep any failed operation with deletion/invitation evidence fail-closed.
- Preserve Companion finalization as the only ownership-release action; do not edit durable records directly.
