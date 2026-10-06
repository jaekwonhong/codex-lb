# Change: Recover account-neutral hard sessions after owner usage exhaustion

## Why

PC1 Codex Desktop can keep a raw legacy `CODEX_SESSION` owner across turns. When an image-capable Astra turn bypasses the HTTP bridge and that hard owner returns a pre-visible `usage_limit_reached`, the direct streaming retry excludes the spent owner but the raw hard mapping still resolves to it. The next selection therefore reports `hard_affinity_saturated: No available accounts` even when another eligible account exists.

API-key streams defer the account-health write until usage settlement, so waiting for the owner row to become `RATE_LIMITED` cannot repair the same in-flight request. The proxy already has source-qualified legacy-owner retirement and account-neutral replay classification; the missing piece is a narrow request-local proof that the exact owner itself just reported account-wide usage exhaustion.

## What Changes

- Carry request-local, owner-specific upstream usage-limit proof through the affinity selection boundary.
- Permit the existing source-qualified legacy owner CAS to use that proof before the deferred durable health write lands.
- Enable this recovery only for pre-visible, account-neutral/self-contained requests and only after the selected owner itself reports usage exhaustion.
- Keep previous-response, conversation, explicit turn-state, file/image owner pins, unresolved tool state, single-account routing, downstream-visible failures, generic rate limits, local caps, and transient transport failures fail-closed.
- Preserve API-key usage settlement before the deferred account-health write.

## Impact

- PC1 Beta Astra turns with self-contained inline images can move to a healthy account after the hard owner exhausts quota instead of collapsing into `No available accounts`.
- Hard continuity remains unchanged for owner-dependent requests.
- The raw owner is retired only for `session_header` interpretation; an explicit `turn_state` lookup using the same text remains owner-bound to the retained account.
