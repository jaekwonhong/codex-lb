## Incident and exact scope

PC2 Beta on 2026-10-11: upstream native WebSocket reader failures occurred after partial output (several hundred to 1,826 events). Some subsequent fresh WebSocket reattachments injected the durable last *completed* response ID and were rejected by the upstream as `previous_response_not_found`.

The provider/network reason for the socket closure is not established by historical data. The already deployed native failure-phase logging and the PC2 API-key `always_http` policy remain the operational protection for that symptom.

## Recovery proof contract

A previously completed ID is not itself a portable upstream anchor after a fresh WebSocket connection. For a delta-only, owner-bound new request, the gateway may reconstruct the complete context from durable completed Responses operations only when:
- The final completed response ID matches the lookup, and **every** turn's session and owner are identical;
- Every operation is completed and each stored SSE spool has a matching `response.completed.response.id`;
- The existing bounded account-neutral projection reconstructs all prior input/answer and current delta, stripping response-owned book-keeping and rejecting unsupported files or dangling tool state;
- A read-only query proves there is **no subsequent operation** (including an older operation updated later) that could have delivered partial output after that completed response;
- The existing owner/account and operation-claim fences remain mandatory and the post-dispatch retry paths are unchanged.

When proof is absent/ambiguous, retain prior owner-bound anchor and existing fail-closed behavior; never silently convert a delta into a contextless fresh request, and never replay an already started tool/action.

The query's anti-join uses an existing operation schema and a single statement snapshot. No migration, credentials, runtime policy change, account switch or quota use occurs as part of this patch.

## Verification

- Before the final repository-head guard refinement: 1,202 HTTP bridge/durable session tests passed; 1,009 native WS, transport fallback, relocation and replay-safety tests passed.
- After the guard refinement: focused SQLite head-proof and real bridge admission/dispatched-frame tests passed, Ruff lint and format PASS, OpenSpec strict PASS.
- The exact production Beta's pre-change source matched the base worktree's `streaming.py`, `durable_bridge_repository.py` and `durable_bridge_coordinator.py` SHA-256. Any live promotion must recheck this.
- Real upstream midstream stream closure is not deliberately recreated; no production quota exhaustion or replay of partially completed tool calls.
