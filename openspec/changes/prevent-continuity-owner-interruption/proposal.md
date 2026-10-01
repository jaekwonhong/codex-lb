## Why

A PC2 Astra continuation repeatedly failed with `previous_response_owner_unavailable`
while other authorized accounts were available. A locally generated ~30-second
rate-limit hold was mistaken for quota recovery even though fresh primary-window
observations still showed exhaustion. The owner retry/retirement paths also used
the full model-generation budget as a recovery wait budget. Waiting longer is not
the requested UX: prevent avoidable submissions and transfer only proven portable
context before dispatch, with short bounded control-plane recovery.

## What Changes

- Keep authoritative throttle deadlines separate from fresh quota/headroom
  admission evidence; an expired local hold alone must not make a freshly
  exhausted account a healthy new-work candidate.
- Reuse existing usage, in-flight lease, policy-scope and headroom rules rather
  than adding a quota predictor, account inventory or new worker service.
- Proactively reuse the existing proof-gated account-neutral full-resend path at
  a completed-turn boundary, before a new response is sent to a pressured owner.
- Prefer zero-delay safe transfer over waiting on long/unknown owner recovery.
  Bound same-owner recovery waiting to two seconds per logical turn and aggregate
  recovery control to five seconds, without truncating normal model generation.
- Preserve structured selection reason/deadline through owner error translation.
  Respect real Retry-After; never accelerate retries on a blocked account.
- Keep file ownership, explicit client anchors, API-key/security scope,
  single-account operator policy, operation fences and uncertain-send no-replay.
- Add deterministic route-level fault injection, concurrency/cancellation and
  regression evidence. No production writes/deployments or credential changes.

## Capabilities

### Modified Capabilities

- `sticky-session-operations`: bounded, provenance-aware owner recovery and safe
  pre-dispatch transfer; existing hard ownership remains mandatory without proof.
- `proxy-admission-control`: fresh quota/headroom-aware admission with existing
  lease accounting and no reservation leaks or scope expansion.

## Impact

Proxy selection/recovery code and tests only. No schema, API-key, OAuth, rotation,
model-source, model/effort, ProviderSwitcher or DGX changes. Implementation is in
an isolated worktree based on qualified integration commit `fb3581ab`.
