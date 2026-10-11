## Grounded failure and guard scope

This narrow change addresses the separate 2026-10-11 17:58 KST PC2 Beta
`gpt-6.1-sol` first-turn quota failure, which returned an upstream HTTP 429 and
logged `failure_class=rate_limit action=surface`. An alternate account
subsequently served the same key and model successfully. We have historical
request metadata and failure logs, **not** a captured unredacted request body,
so the synthetic reproducer tests one demonstrated class of failure without
claiming bit-identical input.

The older 15:19-15:26 hard-owner continuity case remains separate: the failing
account was at 100% primary usage, a different account served another thread,
but the same-thread relocation was refused with `anchor_metadata_missing`.
This change MUST NOT auto-migrate that owner's delta across accounts.

The request-local provisional account claim currently becomes sticky as soon
as a first dispatch is attempted. It is correct for ambiguous or accepted
turns, but prevents the normal bounded failover logic from retrying a request
that received a definitive HTTP-status 429 *before* `response.created`.
The change removes the claim only if the whole request is proven portable.
Unlike a durable transcript recovery, it never reconstructs missing history.

## Evidence

- Red regression before code fix: synthetic Codex transient `client_metadata`
  led to `usage_limit_reached`, `failure_class=rate_limit action=surface`,
  and a propagated HTTP 429.
- Green after code fix: the real streaming entry point with soft prompt-cache
  affinity selects a second account, excludes the failed one, sends no
  original transient thread/turn identity in the replacement body, and
  completes without a delay.
- Negative tests: unknown/malformed transport metadata, prior response,
  account-owned conversation, files, hosted tools, orphaned call results,
  encrypted reasoning, and downstream-visible output fail closed.
- Broad 2026-10-12 suite: HTTP streaming 1,426, HTTP bridge/durable 1,206,
  replay/load-balancer 1,145, WebSocket/native 192 = **3,969 passed**.
  An existing admission-lease GC warning occurred in the HTTP stream suite;
  no test failure resulted.
- Ruff lint/format and active OpenSpec strict validation passed. Existing
  66 main specs passed with legacy length warnings.

## Deployment protection

The 2456 deployed base image and the worktree HEAD source hashes for both
modified production modules match. Ship via immutable file overlay on that
base, retaining all previously deployed WS diagnostics, owner fencing and
proof-backed reattach patches. Do not change PC2 `always_http`, OAuth tokens,
dashboard routing settings, Stable 2455, WMC 2461 or OpenCodex. Do not
intentionally exhaust real quota for a smoke test. Any Beta cutover requires
the existing 5-minute quiet/zero active leases/zero unsafe operation hard gate,
single-writer lock, preserved rollback predecessor and independent attestation.
