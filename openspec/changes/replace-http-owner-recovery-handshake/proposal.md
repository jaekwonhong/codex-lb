## Why

PC2 Beta is intentionally HTTP/SSE-only. When a durable continuation owner hit
quota exhaustion, codex-lb tried to recover a delta-only fresh reattach by
returning `previous_response_not_found` and assuming native Codex would drop the
proxy-injected anchor and resend its complete local history. Production proved
that assumption false for the PC2 Codex Desktop HTTP path: the client surfaced
the error and resent another delta instead of reconstructing the conversation.

The proxy must not depend on an unverified client-side full-history fallback.
Until codex-lb can reconstruct portable context itself, this exact state should
fail before dispatch with an explicit non-retry recovery contract and leave all
other verified replay, file-owner, explicit-anchor, operation-fence and model-
source rules unchanged.

## What Changes

- Replace the quota-owner fresh-reattach `previous_response_not_found` handshake
  with a native-only local pre-dispatch `400 continuity_recovery_required` error when a
  healthy alternate exists but the current delta is not proven portable.
- State clearly that retrying the same HTTP request cannot reconstruct the
  missing context. Preserve the original thread so it can resume if its owner
  recovers, while also offering recovery of a new thread from local Codex
  session history.
- Write the new pre-submit failure to `request_logs` and emit one structured
  bridge event without exposing the raw previous-response id.
- Remove the temporary API-layer exception that exposed a marked
  `previous_response_not_found` only to native Codex; ordinary stale-anchor
  masking and the separate abandoned-operation recovery path keep their existing
  behaviour.
- Add unit and product-path regression coverage proving no upstream dispatch,
  stable error delivery, and request-log attribution.
- Use `invalid_request_error` and an explicit `x-should-retry: false` response
  header for this locally proven refusal. HTTP 409 is not a non-retry contract:
  standard OpenAI SDK retry policies treat it as retryable.
- Require both the native Codex identity and the native backend SSE contract;
  preserve SDK and `/v1/responses` owner-unavailable behavior.
- Attribute the new preflight log only from local pre-dispatch provenance, not
  from a matching error-code string an upstream provider could also return.
- Apply the same no-delta-transfer boundary after a late owner admission failure:
  stale or timed-out advice must not allow legacy retirement to clear a native
  delta's proxy-injected anchor. Reassess alternate availability once within the
  existing recovery/deadline budget, and otherwise keep the original failure.
- Preserve thread attribution for originator-only native identity. For this local
  refusal alone, wait at most one second for the already tracked log insertion;
  keep ordinary request logging detached and never resubmit a timed-out insert.

## Capabilities

### Modified Capabilities

- `responses-api-compat`: explicit HTTP continuity recovery contract for a
  delta-only fresh durable reattach whose owner is unavailable.
- `proxy-runtime-observability`: request-log and structured-event attribution for
  the new recovery-required preflight failure.

## Impact

Beta proxy code and tests only. No database migration, Stable change,
ProviderSwitcher change, WebSocket enablement, model-source/Qwen change, account
credential change, or persistent watcher is introduced.
