# Codebase lifecycle correctness

## Why

The full-codebase review found three executable contract gaps: OAuth-only
enrollment admission rejects its own persisted pending-auth child; background
token rotation does not forward the routing policy accepted by its repository
port; and ordinary OAuth UI responses can outlive the flow that issued them.

## What Changes

- Permit an owning enrollment to advance only its exact, non-pending durable child.
- Forward the existing routing-policy argument through the background repository.
- Fence OAuth UI responses by lifecycle and serialize status polling.
- Keep Companion account-pool memory and catalog at their last committed state when persistence fails.
- Add regressions through production services/repositories and deferred UI requests.
- Preserve the existing member-control extension tables outside the beta.9 upstream Alembic graph and verify them during release rehearsal.
- Refresh stale generated settings documentation and record the existing three-field T1 local extension budget, including the process-local Model Source rollout fence.

## Impact

No schema, credentials, automatic recovery or membership mutation policy changes.
Qualification uses isolated databases and synthetic external services only.
