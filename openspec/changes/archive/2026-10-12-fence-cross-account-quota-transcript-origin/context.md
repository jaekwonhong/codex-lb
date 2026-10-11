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

## 2026-10-12 Beta production qualification

- Fork source commit: `82f5ee90fdebd3694dfb0317bdb20d935a91533e`
  (`fix/hard-owner-quota-transcript-fence-20261012`).
- Immutable Docker overlay based on current live Beta:
  `sha256:020ea6895fa7c273f87a5920419ca390b5f4b1e82e7c4bf7b4db837b98565d2b`.
  Candidate promoted:
  `sha256:d357045072188dd0be83b8c428a68284011d7409f315fee9b493101cedaf407f`.
- Both overlaid production file checksums matched the committed source and
  running container. Imports, inherited first-turn OAuth failover, WebSocket
  diagnostics, same-owner reattach and WMC ownership labels passed.
- Single-writer promotion passed a fresh preflight of zero recent requests,
  active leases and unsafe durable operations; one prior container was stopped
  and restart-fenced for rollback. The new Beta has restart count zero and
  exactly matches the predecessor configuration (except the deliberate
  predecessor restart fence).
- Stable 2455, Beta 2456, WMC 2461 and OpenCodex 10101 returned HTTP 200,
  while PostgreSQL identity/schema and PC2's `always_http` override remained
  unchanged.
- PC2's live bundled Codex CLI, using **command-local**
  `model_provider=codex-lb` so that its default OpenCodex provider was not
  altered, returned the expected sentinel and exit status 0. The Beta request
  database independently recorded `gpt-6.1-sol`, `high`, `http`,
  `success` at 2026-10-11T21:56:22.539516Z.
- No actual `usage_limit_reached` occurred post-promotion. Automatic
  same-thread cross-account recovery under a *natural* quota event therefore
  remains unobserved. Historic absent context remains unavailable, not
  retroactively reconstructed.
- Local deployment receipt:
  `artifacts/pc2-gpt61-sol-high-incident-20261011/hard-owner-quota-transcript-fence-20261012/deployment-result.json`.
