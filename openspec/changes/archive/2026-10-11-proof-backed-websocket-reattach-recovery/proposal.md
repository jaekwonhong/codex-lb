## Why

On 2026-10-11 PC2 Beta, HTTP-to-upstream WebSocket responses ended before response.completed after partial output. The next request attached to a newly created upstream socket; the proxy injected the last *completed* response id (fresh_reattach_anchor_injected), but the provider rejected the previously completed id with previous_response_not_found. Some provider response anchors cannot be resumed across socket lifetimes, and a successful response on the old socket does not prove its anchor is accepted on a new one.

PC2's API-key-only always_http mitigation and subsequent genuine CLI new/resume successes are already deployed and must remain unchanged. The original socket error's physical origin remains unknown; the existing diagnostic phase patch will classify future failures.

## What Changes

- On **fresh WebSocket reattach**, before injecting a prior response id, opportunistically reconstruct an anchor-free request from the *completed*, verified durable operation transcript. Keep the same durable owner account; do not treat reconstruction as cross-account relocation or an accepted-turn retry.
- The reconstruction must prove the last transcript turn belongs to the durable session and owner, terminates at the exact candidate anchor, is completed with an intact spool, and builds an account-neutral, bounded request that includes the client's current input.
- Suppress **all** later durable/session/owner-forward anchor injection paths for that one reconstruction; never add previous_response_id back in a side branch.
- When the transcript is absent, incomplete, foreign, too large or non-portable, leave the existing fail-closed/no-unsafe-replay behavior intact. Do not reset owner, clear durable aliases, infer missing tool outputs, or replay post-dispatch.
- Add focused verifier and HTTP bridge request-path regressions. Do not mutate production credential/transport settings or restart Beta in this change packet.

## Constraints

- No DB schema migration, credential or API key changes.
- No speculative retries after response output or ambiguous dispatch.
- Existing owner/operation claim fences and stale anchor quarantine remain authoritative.
- No claim to fix upstream/network physical WebSocket disconnections. This packet addresses the specific cascade to previous_response_not_found on fresh reattach when complete history is already stored.
