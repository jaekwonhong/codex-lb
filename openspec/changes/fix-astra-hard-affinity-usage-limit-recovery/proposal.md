# Change: Recover account-neutral hard sessions after owner usage exhaustion

## Why

PC1 Codex Desktop can keep a hard continuity owner across turns. When an image-capable Astra turn bypasses the HTTP bridge and that owner returns a pre-visible `usage_limit_reached`, the direct streaming retry excludes the spent owner but the hard raw-session or registered turn-state owner can still constrain the next selection. The retry therefore reports `hard_affinity_saturated: No available accounts` even when another eligible account exists.

API-key streams defer the account-health write until usage settlement, so waiting for the owner row to become `RATE_LIMITED` cannot repair the same in-flight request. The proxy already has source-qualified legacy-owner retirement and account-neutral replay classification; the missing piece is a narrow request-local proof that the exact owner itself just reported account-wide usage exhaustion.

## What Changes

- Carry request-local, owner-specific upstream usage-limit proof through the affinity selection boundary.
- Permit the existing source-qualified legacy owner CAS to use that proof before the deferred durable health write lands.
- Enable this recovery only for pre-visible, account-neutral/self-contained requests and only after the selected owner itself reports usage exhaustion.
- For a registered turn-state owner, permit cross-account replay only when the local bridge that registered that exact alias proves the incoming input prefix and the projected suffix retains the prior output (or exactly settles its pending tool-call manifest); revalidate the same alias/session/anchor at the quota failure before moving.
- Strip the exhausted turn-state token before replacement dispatch and fall back to ordinary thread/session affinity only after that proof succeeds.
- Keep previous-response, conversation, unverified or concurrently advanced turn-state, file/image owner pins, unresolved tool state, single-account routing, downstream-visible failures, generic rate limits, local caps, and transient transport failures fail-closed.
- Preserve API-key usage settlement before the deferred account-health write.

## Impact

- PC1 Beta Astra turns with self-contained inline images can move to a healthy account after the hard owner exhausts quota instead of collapsing into `No available accounts`.
- Hard continuity remains unchanged for owner-dependent or unverified requests; a registered turn-state is movable only with locally verified full-resend evidence and an unchanged alias anchor.
- The raw owner is retired only for `session_header` interpretation; an explicit `turn_state` lookup using the same text remains owner-bound to the retained account.
