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
- [x] Run independent review and non-destructive failure-boundary qualification for the G2/Q2 OFF boundary. The beta.9 review result is recorded in `docs/usage-member-rotation-p7-qualification.md`; the 2026-09-17 Q3 readiness review and follow-up corrections are recorded in `../archive/2026-09-17-rotation-dispatch-evidence/context.md`. This does not close Q3 dispatch admission.
- [x] P7: freeze the non-destructive failure-boundary matrix against the G1 public boundary and durable repositories.
- [x] P7: provide restart/no-replay adapter protocols for reset, remove, and invite, including a replay-unsafe negative control.
- [x] P7: provide exact candidate/P4 provenance, read-only deployment preflight, rollback-state preservation, feature-OFF, and live-canary guard tooling.
- [x] P7: replay/hash the frozen P4 artifact, run the qualification suite, and complete independent review without live effects.
- [x] G2: connect the P5 durable controller to the P6 operator read model without scheduler/effect authority.
- [x] Q2 closure: keep the four rotation tables outside official Alembic, require fail-closed PostgreSQL extension startup validation, and preserve the beta.9 official `20260913_000000_add_oidc_provider_flow` shared head.
- [x] Q2 closure: bind P7 beta.9 migration/runtime evidence to the post-migration DB snapshot, prove exact beta.7 predecessors reject that beta.9 epoch as ahead/unknown, and prove rollback with a catalog-preserving `pg_basebackup`/physical restore that retains the `20260910...` source system identifier, predecessor local-extension catalog representation, all six extension-table data fingerprints, and exact Stable/Q2-Beta runtime-start/readiness after the restored DB epoch; logical `pg_dump`/`pg_restore` alone is not rollback authority.
- [x] Q2 closure: require the beta.9 candidate to use a new runtime-bound image/source/tree first-start gate with exact entrypoint bytes, atomic no-overwrite publication, same-PID1/netns release proof, fail-closed ambiguous publication, and no reuse of the historical Q2 sentinel.
- [x] Establish the qualified P4 Companion on the host and verify its running binary. The 2026-09-17 read-only LaunchAgent/PID/inode/hash verification passes for 2.11.47; this observation alone is not a backend dispatch provider.
- [x] Implement and locally qualify current host-verified Companion provenance at the backend dispatch boundary and the default-off server-owned single-evaluation scheduler. Source evidence: `../archive/2026-09-18-rotation-runtime-dispatch/context.md`. Signer and read-only trust-root provisioning completed with the matched OFF deployment on 2026-09-19. Plan activation remains conditional on fresh Q3 admission.
- [x] Implement and locally qualify the single-workflow canary budget at the actual Companion remove and invite boundaries, with removal reconciliation before invitation, and retain typed removal telemetry on the managed-operation path. Candidate `2.11.48-canary.1` was built reproducibly and deployed OFF on 2026-09-19 (binary `1ec90e2b...`, canonical source manifest `b6f6c753...`); historical implementation evidence: see `../archive/2026-09-17-companion-canary-effect-boundaries/context.md`.
- [x] Build isolated backend and reproducible Companion 2.11.48-canary.1 artifacts and verify OFF startup. See `../../specs/member-switch-commands/build-qualification-20260918.md`; this is not dispatch/release admission.
- [x] Re-evaluate and locally qualify the rotation delta against current Beta `62cd34ce` on 2026-09-19, preserving subsequent fixes and registering exact Companion artifact/source identity. See `../archive/2026-09-19-rotation-current-artifact/context.md`; Current-data PostgreSQL qualification and matched OFF deployment subsequently passed; see `../../specs/member-switch-commands/off-deployment-20260919.md`.
- [x] Qualify and deploy matched backend `c409eac1...` / Companion `2.11.48-canary.1` with current artifact provenance; install the external signer and read-only public trust root, preserving OFF and durable state. No canary plan is published. The historical 2.11.47 P4 tuple is not used to qualify the new binary.
- [x] Deploy Beta with automatic rotation disabled and verify read-only/runtime compatibility. Historical deployment: `4acf0d9f`, beta.9, sealed production result `artifacts/beta9-production-cutover-4acf0d9f-20260917T024043Z/production-cutover-final.json` in the operations workspace. Later source edits require separate qualification/deployment.
- [ ] Conditional Q3 live canary remains NOT RUN / NOT ADMITTED. Historical 2026-09-19 preflight failed `five_hour_missing` despite Weekly 100%; explicit same-fetch absence support was subsequently delivered in the 2026-09-20 b98 OFF release, not a new Q3 approval. No reset/remove/invite, plan or enabled intent was issued. All current prerequisites must pass before the existing at-most-one budget may be used; a successful normal reset must prevent replacement.

- [x] Q4 release decision completed on 2026-09-19: NO-GO for automatic release, retain the matched pair OFF. Current host operations, isolated recreation/recovery and final independent audit passed. Q3 remains NOT RUN / NOT ADMITTED above. Evidence: `../archive/2026-09-19-rotation-matched-off-deployment/context.md` and `../../specs/member-switch-commands/off-deployment-20260919.md`.

## Subsequent current-source work

- [x] 2026-09-20 optional-5H/P2 Beta-only OFF replacement and separate OpenSpec archive synchronization completed. Last admitted Beta is b98/e55; immediate retained predecessor is 817ca6d0/c409. See `../../specs/member-switch-commands/off-deployment-20260920.md` for the generation-specific read-only observer; historical c409 recreation tooling must not be reused.
- [x] Correct and locally requalify the six source-review findings under `rotation-epic-review-corrections` (including the late operator wire-schema P1). Backend 682 and panel 27 tests passed; actual ASGI-to-client checks, lint/type/spec verification and independent source review are recorded in `artifacts/rotation-epic-corrections-20260922T090210Z` in the operations workspace. Local source qualification does not redeploy b98, change its manifest, or authorize Git commit/merge or Q3 activation.
