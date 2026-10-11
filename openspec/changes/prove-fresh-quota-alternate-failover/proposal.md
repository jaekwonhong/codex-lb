## Why

PC2 Beta on 2026-10-11 returned usage_limit_reached on the same account ten times at 15:19-15:26 KST. Other OAuth capacity demonstrably existed (the same PC2 API key and model succeeded on a different account seven times). A separate first-turn HTTP request at 17:58 returned 429 with Failover decision failure_class=rate_limit action=surface despite prior proof that an alternate account worked.

The HTTP-bridge hard-owner case refused reconstruction with anchor_metadata_missing; that refusal protected conversation context and cannot be safely overturned. This change targets ONLY a first-turn HTTP streaming request that can be proven to have an account-neutral, self-contained fresh body after safe removal of transient client routing metadata. It must not discard existing conversation/tool state, double-execute output, or weaken prior owner claims.

## What Changes

- Prepare a strict, bounded account-neutral fresh projection for a first-turn Responses request whose only nonportable top-level metadata is an explicitly known transient Codex client identity. Unknown metadata and account-scoped references remain nonportable.
- On an upstream definitive 429 usage_limit_reached BEFORE any response event/output and when no stored previous response, turn-state owner, file owner or hard preferred account is present, use the projection to unlock the request-local provisional payload owner and allow a single bounded alternative-account selection. Existing reservation settlement and health-write ordering remain authoritative.
- No new automatic replay after a response ID or token has been sent to the client. No replay across hard account ownership or explicit single_account strategy. Failed proof retains the original 429 and does not exclude the only valid owner.
- Add end-to-end streaming retry-path regression tests for safe quota alternate and no-replay negative cases.

## Non-goals

- No automatic migration of a partially completed tool call or a historical thread whose anchor metadata is missing.
- No source-wide relaxation of quota priorities, account status or burn_first routing.
- No forced real quota exhaustion, credential changes, or Beta runtime changes before independent validation and safety preflight.
