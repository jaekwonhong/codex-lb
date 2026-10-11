## Implementation

- [x] Add strict pure durable transcript origin+completion checker shared with same-owner reattach.
- [x] Require read-only uninterrupted-head proof before definitive quota relocation dispatches reconstructed durable history.
- [x] Preserve original failure when proof is missing, mismatched or raises.

## Verification

- [x] Reproduce mismatched owner/session/incomplete/spoofed terminal/newer operation in HTTP-bridge integration tests.
- [x] Preserve safe, complete transcript migration even when old anchor item-count metadata is unavailable.
- [x] Verify independently portable full-resend path, single-account/file/turn ownership and existing pre-visible safety gates.
- [x] Run OpenSpec strict, unit and bridge/WebSocket/stream regressions; attest fork-only commit.
- [x] Re-qualify immutable current-Beta-overlay image, safe rollback and PC2 session policy; deploy only if all production gates pass.
