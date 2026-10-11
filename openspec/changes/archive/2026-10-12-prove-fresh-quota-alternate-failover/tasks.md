## Implementation and verification
- [x] Capture deterministic historical first-turn 429/provisional owner regression using streaming entrypoint.
- [x] Add pure account-neutral fresh-projection helper with strict allowlist of transient Codex metadata only.
- [x] Wire definitive precreated quota failure to bounded alternate retry only when projected body is safe and pre-response status is proven.
- [x] Cover hard-owner, file, turn-state, previous-response, unrecognized metadata, output-visible and generic 429 negatives.
- [x] Run HTTP-stream, HTTP-bridge, websocket and replay-safety tests; validate OpenSpec and static lint.
- [x] Independently reapply onto current Beta immutable parent and qualify canary/rollback before production decision.
