## 1. Baseline and contract
- [x] 1.1 Read repository rules and existing admission/owner-recovery contracts.
- [x] 1.2 Create isolated branch from fb3581ab and record this final OpenSpec plan.
- [x] 1.3 Identify all affected live serialization/selection paths and falsifiable regressions.

## 2. Implementation
- [x] 2.1 Keep fresh quota/headroom evidence across default cooldown expiry without policy bypass.
- [x] 2.2 Implement typed owner recovery evidence and short cumulative budgets.
- [x] 2.3 Connect pre-dispatch transfer only through existing complete-context and operation fences.
- [x] 2.4 Retain error provenance and Retry-After, cancellation and lease settlement.

## 3. Verification
- [x] 3.1 Deterministic unit and route-level tests for short/long waits, exhaustion, proof rejection and uncertain send.
- [x] 3.2 Concurrency/cancellation/replica admission regression and no duplicate submission tests.
- [x] 3.3 Relevant full suites, Ruff/format/type/architecture and strict OpenSpec.
- [x] 3.4 Independent review where available; document findings, limits and fixes.
- [x] 3.5 Final handoff with exact tested tree, source/deployment distinction and remaining gates.

### Qualification record

- Focused owner-recovery and product-path tests: 84 PASS on the final tree.
- Related account-selection, HTTP bridge, streaming, direct HTTP and WebSocket suites:
  3,386 PASS on the final tree.
- OpenAI error/request serialization suites: 218 PASS on the final tree.
- Ruff, format, ty, proxy architecture, strict OpenSpec and `git diff --check`: PASS.
- The earlier full HTTP-bridge run exposed two expectation mismatches after the new
  fail-before-dispatch behavior; both were inspected and corrected, then covered by
  the final focused and 3,386-test qualification.
- Chat On Steroids independent worker review was attempted twice but unavailable
  because the connector could not recover worker identity. No worker finding is
  claimed. A manual diff review plus the automated gates above form the review
  evidence for this isolated candidate.
- This qualification is source-only. No production container, database, credential,
  ProviderSwitcher, DGX or account state was changed by this implementation.
