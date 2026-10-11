## Implementation
- [x] Validate complete same-owner/same-session durable transcript and reconstruct a bounded, anchor-free fresh request.
- [x] Integrate before fresh reattach anchor injection and fence secondary injection paths without changing owner/account and retry semantics.
- [x] Add positive and fail-closed proof tests, plus bridge dispatch tests that show the actual outgoing upstream frame is anchor-free.
## Verification
- [x] OpenSpec change and specs validation.
- [x] Focused and existing complete HTTP-bridge unit regression.
- [x] WebSocket/native helper regression.
- [x] Qualify image overlay and safe operational decision with PC2 always_http preserved.
