## 1. Implementation

- [x] Carry request-local proven owner usage-limit evidence through affinity and selection.
- [x] Reuse the source-qualified legacy-owner tombstone CAS without requiring the deferred durable status write to land first.
- [x] Arm recovery only for pre-visible account-neutral requests and preserve all hard-owner exclusions.
- [x] Add registered turn-state recovery only for locally verified full-history replay and revalidate the alias/session anchor before failover.

## 2. Verification

- [x] Add request-path regression for an inline-image Astra-shaped stream with API-key settlement ordering.
- [x] Add direct-stream regression for a registered `http_turn_*` alias with verified retained history, plus incomplete/account-scoped rejection coverage.
- [x] Add load-balancer coverage for retirement while the durable account row is still active.
- [x] Add repository coverage proving source-qualified tombstone semantics and explicit-turn-state preservation.
- [x] Run focused and broad proxy/sticky regression suites, Ruff, ty, diff checks, and strict OpenSpec validation.
- [x] Close direct-HTTP selection-time owner-quota failover through the shared relocation verdict and add a regression that proves the verdict is invoked.
- [x] Add an end-to-end HTTP-bridge regression for owner `usage_limit_reached` -> account-neutral full-resend relocation -> next-turn continuity on the replacement account, including durable-operation re-fencing.
- [x] Preserve generic configured required-account semantics while retaining definitive quota provenance only for ownership/continuity-constrained selection.
