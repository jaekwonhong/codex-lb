## 1. Contract

- [x] 1.1 Record the production failure mode and the HTTP-only client limitation.
- [x] 1.2 Define the exact recovery-required boundary and retained fail-closed cases.

## 2. Implementation

- [x] 2.1 Add the explicit continuity-recovery-required error envelope.
- [x] 2.2 Replace only the quota-owner fresh-reattach client-history handshake.
- [x] 2.3 Remove the temporary native previous-response unmasking exception.
- [x] 2.4 Include the new failure in bridge preflight request-log attribution.

## 3. Verification

- [x] 3.1 Unit regression for the production fresh-reattach delta shape.
- [x] 3.2 Route-level regression proving HTTP 409, no upstream dispatch, and one request-log row.
- [x] 3.3 Existing owner interruption, HTTP bridge replay, stale-anchor masking and model-source regressions pass.
- [x] 3.4 Ruff, format, diff check and strict OpenSpec validation pass.

### Qualification record

- Production-shape owner interruption route suite: 10 PASS.
- HTTP bridge owner/replay/reattach focused suite: 45 PASS; full-resend owner/replay/reattach integration subset: 25 PASS.
- API stale-anchor/error-shaping suite: 28 PASS; model-source WebSocket guard suite: 18 PASS.
- Changed proxy application files pass targeted `ty check`; Ruff, format and `git diff --check` pass.
- Strict OpenSpec change validation passes; main spec tree: 66 PASS, 0 FAIL.
- Repository-wide `ty check` and the proxy timing-seam guard already fail on the unchanged 8f41ee0ea baseline. The baseline has 71 type diagnostics and the same two raw-clock timing findings; this change does not widen either gate. Proxy architecture and cancellation-safety guards pass.

## 4. Deployment

- [ ] 4.1 Build a minimal Beta derivative only after all gates pass.
- [ ] 4.2 Preserve rollback container and verify readiness; leave Stable untouched.
