## S0/S1 foundation

- [x] Freeze the current ops/Beta/Stable/PostgreSQL/Companion baseline without modifying the dirty vendor checkout or live runtime.
- [x] Define the Weekly-window evidence contract, including slot-independent classification, per-window freshness, raw-value exhaustion, elapsed-reset handling, and `fetch_succeeded` vs `usage_written`.
- [x] Define reset-credit resolution around the existing authoritative serialized/idempotent redemption path and bounded post-redeem reconciliation.
- [x] Define local rolling limits as 24H max 3 and 168H max 7 inclusive, with attempted/effect/completed/unknown states kept distinct.
- [x] Define immutable removed-member Usage retention and cutoff-based Reset-schedule invalidation without clearing historical facts.
- [x] Define typed, sanitized, separate remove/invite telemetry and no-replay behavior for response ambiguity.
- [x] Define P1-P4 parallel ownership and the no-live-effect qualification boundary.

## Parallel Wave 1

- [x] P1: implement and test classified fresh Weekly observations without membership/reset side effects.
- [x] P2: implement and test authoritative reset-credit resolution by reusing central redemption coordination.
- [x] P3: implement and test rolling quota/effect accounting, final member Usage retention, and Reset-schedule invalidation.
- [x] P4: implement and test typed sanitized remove/invite Companion telemetry without live membership effects.

## Fan-in and later work

- [x] Integrate P1-P4 on a clean integration branch and run cross-epic foundation tests.
- [x] Implement the server-owned rotation controller only after the foundation integration passes.
- [x] Implement the default-off operator UI and read-only status API from the stable G1 read-model boundary, with an additive P5 snapshot adapter and intent-only toggle.
- [ ] Run independent review and non-destructive failure-boundary qualification.
- [x] P7: freeze the non-destructive failure-boundary matrix against the G1 public boundary and durable repositories.
- [x] P7: provide restart/no-replay adapter protocols for reset, remove, and invite, including a replay-unsafe negative control.
- [x] P7: provide exact candidate/P4 provenance, read-only deployment preflight, rollback-state preservation, feature-OFF, and live-canary guard tooling.
- [x] P7: replay/hash the frozen P4 artifact, run the qualification suite, and complete independent review without live effects.
- [x] G2: connect the P5 durable controller to the P6 operator read model without scheduler/effect authority.
- [x] Q2 closure: keep the four rotation tables outside official Alembic, require fail-closed PostgreSQL extension startup validation, and preserve the beta.9 official `20260913_000000_add_oidc_provider_flow` shared head.
- [x] Q2 closure: bind P7 beta.9 migration/runtime evidence to the post-migration DB snapshot, prove exact beta.7 predecessors reject that beta.9 epoch as ahead/unknown, and prove rollback with a catalog-preserving `pg_basebackup`/physical restore that retains the `20260910...` source system identifier, predecessor local-extension catalog representation, all six extension-table data fingerprints, and exact Stable/Q2-Beta runtime-start/readiness after the restored DB epoch; logical `pg_dump`/`pg_restore` alone is not rollback authority.
- [x] Q2 closure: require the beta.9 candidate to use a new runtime-bound image/source/tree first-start gate with exact entrypoint bytes, atomic no-overwrite publication, same-PID1/netns release proof, fail-closed ambiguous publication, and no reuse of the historical Q2 sentinel.
- [ ] Post-G2 release gate: establish authoritative runtime P4 Companion provenance and connect the default-off server-owned scheduler before any live automatic canary.
- [ ] Deploy Beta with automatic rotation disabled and verify read-only/runtime compatibility.
- [ ] When a real operational replacement is needed, run at most one final live canary; do not force a replacement if a legitimate reset credit restores Weekly usage.
