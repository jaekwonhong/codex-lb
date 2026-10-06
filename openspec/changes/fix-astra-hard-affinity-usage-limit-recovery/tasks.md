## 1. Implementation

- [x] Carry request-local proven owner usage-limit evidence through affinity and selection.
- [x] Reuse the source-qualified legacy-owner tombstone CAS without requiring the deferred durable status write to land first.
- [x] Arm recovery only for pre-visible account-neutral requests and preserve all hard-owner exclusions.

## 2. Verification

- [x] Add request-path regression for an inline-image Astra-shaped stream with API-key settlement ordering.
- [x] Add load-balancer coverage for retirement while the durable account row is still active.
- [x] Add repository coverage proving source-qualified tombstone semantics and explicit-turn-state preservation.
- [x] Run focused and broad proxy/sticky regression suites, Ruff, ty, diff checks, and strict OpenSpec validation.
