## 1. Characterize the replay boundary

- [x] 1.1 Add pure helper tests covering non-empty reasoning content, invalid reasoning IDs, valid empty-content `rs_` items, encrypted reasoning state, absent IDs, non-reasoning item preservation, and idempotence.
- [x] 1.2 Add subscription serialization regression tests for core HTTP/websocket, direct websocket `response.create`, size-guarded resend, and HTTP bridge paths; keep model-source forwarding unchanged.

## 2. Implement subscription egress normalization

- [x] 2.1 Add one pure request-payload helper that removes only non-portable reasoning input items without mutating the reusable request model.
- [x] 2.2 Apply the helper before payload sizing/serialization in core subscription HTTP/websocket transport.
- [x] 2.3 Apply the helper before payload sizing/serialization in direct websocket and HTTP bridge `response.create` paths, including fresh-resend/retry bodies.

## 3. Verify behavior

- [x] 3.1 Run focused unit/integration tests, then relevant full Responses proxy/websocket/HTTP-bridge suites.
- [x] 3.2 Run changed-file Ruff/format/type checks, proxy architecture checker, and `git diff --check`.
- [x] 3.3 Run strict OpenSpec validation and an isolated Qwen → Astra same-thread qualification proving the prior `array_above_max_length` failure is gone.
- [x] 3.4 Prepare a reviewable deployment candidate and document remaining production rollout approval; do not deploy from this worktree without explicit approval.
