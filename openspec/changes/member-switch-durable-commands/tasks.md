## Ordered implementation

- [x] Separate stored auth observation from explicit advancement.
- [x] Establish durable run/command admission and restart-safe child receipts.
- [x] Implement the explicit manual state machine and server-backed UI recovery.
- [x] Split Companion decisions and operation storage from browser orchestration.
- [x] Evaluate automation qualification; NOT QUALIFIED, automatic mutation remains disabled.

## Verification

- [x] Run fake-service, ASGI route, persistence, migration and concurrency tests.
- [x] Run frontend type/lint/build/tests and intercepted browser checks.
- [x] Run Companion fake-driver tests; no live browser or account work. Existing skips are not passes.
- [x] Replay patches, record input/output hashes and document limitations.
