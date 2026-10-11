## PC2 incident and scope

On October 11 a quota-exhausted OAuth owner could not safely serve an existing
PC2 Codex thread. Other accounts had capacity, but the observed replay
rejection was `anchor_metadata_missing`. That rejection alone supplies no
portable request body. The 2026-10-12 first-turn fix (dc2de65a0) does not
automatically transfer this earlier delta-only thread.

On October 12 the live Beta 2456 durable database was read *without writes*.
Of 92 retained sessions naming a response anchor, none lacked the stored
input count or fingerprint. This current aggregate does not prove the October
11 failing thread had an intact transcript; the original request/response
materials were not recovered, and historical context cannot be fabricated.
No natural `usage_limit_reached` request was recorded after the prior Beta
patch at the time of this investigation.

## Security/continuity decision

Existing `decide_relocation` validates body replayability and linked response
IDs but does not prove the origin of a durable transcript. The separate
same-owner reattachment implementation already knows how to verify session,
OAuth account, completed operation, exact `response.completed` ID, and
read-only absence of newer operations. Sharing this proof closes a silent
cross-account history contamination or lost-interrupted-turn gap.

The body may have been rebuilt once for a fresh socket. In that case the
common relocation verdict can label the already complete body `client_input`
even though the missing context came from durable history. The quota lane
therefore tracks *how that request was built* and re-reads the uninterrupted
operation head just before permitting an alternate account. An independently
self-contained client resend that requires no durable context is unaffected.

The change is deliberately a stronger proof gate, not a relaxation of
`anchor_metadata_missing`, not a repair of unrecorded old context, and not a
reason to use an exhausted OAuth account again.

## Verification

- A synthetic, definitive owner quota was able to move foreign-account
  durable output in the old code (red HTTP-bridge regression).
- A separate red regression proved that owner admission could invalidate a
  previously true head check before a second-account replay.
- The revised tests permit verified complete historical input (including a
  historical durable row without stored input-count metadata) and reject
  foreign session/account, incomplete operation/spool, foreign terminal,
  superseded response and failed head lookup.
- Targeted HTTP bridge and reattachment tests passed. Broad regression
  totals: HTTP bridge+durable 1,218; HTTP streaming 1,426; replay/balancer
  1,145; WebSocket/native 192 — **3,981 passed**. Ruff and OpenSpec strict
  checks passed. An existing admission-lease garbage-collection warning
  remained, with no test failure.

## Deployment constraints

Preserve PC2 `always_http`, all OAuth account material, Beta 2456's previous
patch labels, Stable 2455, WMC 2461 and OpenCodex 10101. Only replace the two
HTTP-bridge Python modules on the exact running immutable Beta parent. A
candidate may be promoted only after offline hash/import validation,
single-writer cutover lock, zero recent ingress, zero live leases and zero
unsafe durable operations. Keep the exact predecessor stopped and
restart-fenced for rollback. Never force real token-quota exhaustion.
