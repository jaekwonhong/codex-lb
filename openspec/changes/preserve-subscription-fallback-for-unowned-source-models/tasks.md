## 1. Specification

- [x] 1.1 Define positive assigned-source ownership as the fail-closed boundary for registry-missing Responses models on source-scoped API keys.
- [x] 1.2 Preserve structural subscription routing, continuity-suppressed subscription ownership, exact API-key model allowlisting, and dangling-scope fail-closed behavior.

## 2. Implementation

- [x] 2.1 Add a read-only repository ownership query over the key's explicitly assigned sources, independent of enablement/capability after ordinary and disabled source lookup have missed.
- [x] 2.2 Make the final source-only guard use positive ownership rather than registry absence alone, while retaining the empty-assignment safety boundary.
- [x] 2.3 Skip that guard for source-route exclusions and continuity-suppressed turns.

## 3. Regression coverage

- [x] 3.1 A registry-missing Astra-like subscription slug not declared by the assigned source reaches subscription routing on both Responses HTTP surfaces.
- [x] 3.2 A model actually declared by the assigned source remains fail-closed when no valid Responses source route exists.
- [x] 3.3 The runtime-enabled disabled DGX source still routes its assigned model and does not broaden to unrelated subscription models.
- [x] 3.4 Source-scoped file-pin and continuity-suppressed recorded-subscription-owner requests retain their existing subscription routing.

## 4. Validation

- [x] 4.1 Run focused and full model-source routing regressions plus relevant dispatch/model/WebSocket source-guard suites.
- [x] 4.2 Run Ruff, formatting, type checks, and strict OpenSpec validation.
- [ ] 4.3 Build an immutable Beta image from the committed tree and verify Astra HTTP success, DGX scoped selection, readiness, PostgreSQL health, rotation OFF, and no member/OAuth effects in production.
