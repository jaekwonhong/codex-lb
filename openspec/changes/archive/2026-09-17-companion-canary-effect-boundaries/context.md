# Companion canary effect boundaries — 2026-09-17

This verified source change closes the Companion effect-budget and managed
removal-telemetry gaps. It does not authorize or implement a live Q3 run.

## Candidate and compatibility

The candidate is `2.11.48-canary.1`, copied from the frozen 2.11.47 P4 source at
`artifacts/q2-usage-member-rotation-20260914/companion-2.11.47-source-a` in the
operations workspace. Its source, patch, hashes, and logs are preserved under
`artifacts/rotation-canary-boundaries-20260917/`. The frozen source is unchanged.
Backend edits remain uncommitted on baseline
`4acf0d9fffd99b5c8677dbed5df460c5ef04f7bd`, together with the preceding dispatch
evidence corrections. Neither candidate has been deployed.

Canary selection defaults false. It requires the dedicated managed-protocol
`/canary-operations` endpoint and a matching request flag. This prevents an old
runtime from ignoring a new JSON field and executing an ordinary operation.
There is no fallback to `/operations` after rejection.

## Durable ordering and uncertainty

The durable receipt store binds one canary workflow for its retained lifetime.
It saves a distinct claim immediately before each browser DELETE/Invite call.
Invite additionally requires the exact bound outgoing identity and persisted
authoritative outgoing-absence trace. A claim is never refunded by failure,
completion, release, or elapsed time. Reconstructed stores reject even unused
claims, and reads or duplicate starts never resume background work.

The existing manual verifier can retry a definitive `404/member_identity_missing`
DELETE. Canary disables that retry. For example, if the first DELETE returns
that code while inspection still sees the outgoing member, the canary ends with
one DELETE and zero invites. Lost responses likewise never grant replay authority.

The managed operation preserves sanitized delete telemetry through later states
and reconstruction. Backend projection retains it separately from invitation
evidence. Number, boolean, and null fields retain their JSON types; capture
uncertainty remains visible and can put the controller into needs-attention.

## Store rollback boundary

Ordinary receipts stay at schema 1. The first canary binding writes schema 2;
the old 2.11.47 runtime rejects it rather than erasing the spent budget. Preserve
the current receipt store through rollback and reconciliation. Restoring an old
store or starting with an empty store is not permission to replenish a canary
budget. The store assumes the existing single-process LauncherInstance ownership.

## Verification

- Companion full suite: 573 passed, 23 existing skipped, zero failures.
- Backend rotation qualification: 322 passed; included Ruff, ty, strict primary change validation.
- Backend Companion client suite: 13 passed; additional Ruff and ty checks passed.
- Independent implementation review: PASS after the verifier retry correction;
  reviewer reran 55 Companion boundary/canary tests and five backend focused cases.
- Tests cover durable before-call ordering, duplicate/concurrent claims, release,
  restart, failed writes for both claims, lost delete/invite replies, endpoint
  mismatch, no transport fallback, and typed telemetry retention.
- Existing platform/analyzer warnings and 23 legacy skipped tests are not claims
  of successful Windows or live-browser qualification.

## Remaining Q3 gates

The deployed Q2 Beta remains OFF at its prior release. Current host provenance
still identifies 2.11.47; its qualified P4 hash/version tuple is unchanged and does
not certify this candidate. Remaining work is a current host-attestation provider
at backend dispatch, a default-off server scheduler with explicit bounded canary
selection, matched candidate build/provenance/release qualification and deployment,
then legitimate operational eligibility before at most one live canary. No real
membership, reset, or live browser effect was performed by this source work.
