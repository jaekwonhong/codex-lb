# Context

## S0 frozen baseline — 2026-09-13 KST

The foundation branch is cut from the source revision currently named by the live Beta container, not from the dirty convenience checkout under `vendor/`.

- Operations repository `main`: `97becd4b66a5569efd3895d10ff7c9beec3eea97` (`fix(ops): deploy owner OAuth UI cleanup`).
- Live Beta integration revision: `ace3be6125969e02a4c0d6b284f236a31914c814`.
- Live Beta image: `sha256:3c7bf99fd01b899568fe7e0da3dfa9712b83013e4ce7887b8be1f2be1d88e370`; healthy; restart count 0 at freeze time.
- Live Stable image: `sha256:45d858e44e020f814011e4df23151bd455396d61c928fc9fda5e75d889aa8be4`; healthy; restart count 0 at freeze time.
- Live PostgreSQL image: `sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2`; healthy; restart count 0 at freeze time.
- Live Companion SHA advertised by Beta: `9e74d21f5bd912327d674e4704d8a4a9e01c038d7983128993d89238c2057228`.
- Live member-switch mode: `manual-only`.
- Live Beta advertises the existing Business member removal observation release capability.
- Stable and Beta share PostgreSQL; feature work therefore treats database and external membership effects as shared-state boundaries even when code work is isolated.

No container, database row, OAuth state, reset credit, membership, invitation, or seat quantity is changed by S0/S1.

## S1 shared interpretation contract

### Weekly usage is evidence, not a slot name

`primary` and `secondary` are storage/presentation slots, not universal meanings. A Weekly exhaustion decision must identify the actual weekly window from the current payload shape and window metadata. A weekly-only plan can arrive in `primary` and be normalized for downstream display. Monthly-only presentation can suppress other displayed windows. Therefore the rotation foundation consumes a classified Weekly observation rather than reading `secondary_remaining_percent == 0`.

The observation records its exact member/account mapping, source slot, raw used percentage, window duration, reset timestamp, observation timestamp, and fetch provenance. `fetch_succeeded` and `usage_written` remain distinct: a successful fetch that produces no database change is fresh evidence; a failed fetch that leaves old rows visible is not. Missing values, JSON/data `null`, placeholders, unclassified windows, and failed fetches are unknown, never exhausted. If a prior exhausted window's reset deadline has elapsed, the old zero/100% state cannot authorize rotation; a fresh upstream observation is required.

### Reset credit resolution reuses the central authority

The account-summary/usage-reset-credit convenience surface can present missing credit information as zero and is therefore not authoritative evidence that no credit exists. Rotation must resolve credit availability through the current reset-credit detail/redemption subsystem and reuse its shared-database serialization, durable `(account_id, redeem_request_id)` pin, selected-credit identity, cache invalidation, and cross-replica coordination. It must not add a second reset executor.

One exhausted-member evaluation can attempt at most one reset-credit redemption under one stable redeem request id. A top-level convenience `status="reset"` is not sufficient evidence of recovery. The response code, `windows_reset`, and bounded fresh Weekly re-observation are separate evidence. A zero shown immediately after redeem can be propagation delay or stale data. If bounded reconciliation cannot prove either recovery or a safe no-reset condition, rotation stops in an attention/pending state. It never consumes another credit merely to complete a test or clear ambiguity.

### Internal replacement limits are local safety policy

The initial internal policy is a rolling maximum of three admitted replacement operations per workspace in the preceding 24 hours and seven in the preceding 168 hours; the third and seventh operations are allowed. A possible upstream limit of roughly ten changes is an unverified hypothesis and is not an admission value.

The ledger keeps request attempts, externally possible effects, confirmed effects, and business-level completion separate. An operation that may have crossed a removal/invite effect boundary consumes/reserves an internal quota slot until authoritative reconciliation proves a safe non-effect. A lost or malformed reply does not return the slot. A removal that is confirmed while its invite fails is not erased merely because the overall replacement did not complete. Counts derived from a ledger that does not cover all possible historical/manual changes are labeled observed/local counts rather than OpenAI-actual counts.

Any current undocumented server fields (for example vacancy/replacement ordinals, thresholds, expiries, notices) remain sanitized telemetry until their scope, time window, action boundary, and semantics are repeatedly verified. A server number larger than the local limit does not automatically loosen the local policy. Billing fields such as `billed_seat_delta` are never replacement-count inputs.

### Historical usage survives membership removal and reset-schedule cleanup

Before a removal is authorized, the outgoing member's latest classified 5H and Weekly observations are durably retained with their original raw usage values, window metadata, reset timestamps, observation timestamps, and provenance. Removal must not make those facts disappear or allow a later account reuse to overwrite the historical membership-period evidence.

A user action that clears historical Reset schedules is not a reset-credit consume and is not proof OpenAI changed usage. It records an invalidation with a fixed cutoff. Original snapshot values and original reset timestamps remain immutable evidence; only the effective/display reset schedule for snapshots at or before the cutoff becomes absent. The action does not rewrite usage to 100%/0%, clear member-change counts, delete unknown operations, or consume a reset credit. Snapshots created after the cutoff are unaffected.

### Remove and invite telemetry are separate typed observations

The trusted Companion captures sanitized response evidence for owner-side remove and invite as separate events. JSON primitive types are preserved (`5` remains a number, `true` a boolean, JSON `null` null). The envelope distinguishes field absence, JSON null, an empty body, parse failure, no response received, and transport failure. Capture/redaction failure never authorizes replay of a membership mutation.

Sanitization is recursive through objects, arrays, and dynamic keys. Raw response bodies, HARs, cookies, authorization/CSRF/session material, email addresses, raw user/member/workspace/account/invite/payment identifiers, and unrestricted arbitrary strings are not retained. Invite transmission is not join completion; join remains a separate effect/observation boundary.

## Parallel implementation ownership after S1

P1-P3 branch from the exact committed S1 HEAD in the Beta source repository. P4 is a Companion/operations epic and therefore branches independently from the frozen operations baseline while reconstructing the exact currently deployed Companion source identified by the live Companion SHA; P4 treats this S1 OpenSpec change as its normative contract. No epic develops in the dirty `vendor/codex-lb-beta-source` checkout. The epics must not merge/rebase each other while developing and must return a focused commit plus validation evidence for a later product/operations integration gate.

- **P1 Weekly Usage Observation** owns Weekly classification/freshness/provenance and focused tests under usage modules. It does not consume reset credits or invoke member switching.
- **P2 Reset Credit Resolution** owns the rotation-facing reset-resolution adapter around the existing rate-limit reset-credit authority. It does not decide Weekly classification, member quota, or membership effects.
- **P3 Quota / History / Retention** owns rolling replacement accounting, effect/reservation ledger semantics, outgoing final snapshots, and reset-schedule invalidation. It does not call Companion/member mutations or implement reset-credit redemption.
- **P4 Companion Typed Telemetry** owns the deployed-Companion-side remove/invite typed sanitized response envelope and no-replay observation tests. It does not implement the automatic controller, choose candidates, or perform live member effects.

Shared cross-epic DTOs/contracts introduced in S1 are not to be redefined independently. If an epic proves the S1 contract is insufficient, it stops and records the required contract change for the integration owner rather than silently changing semantics in its branch.

## Qualification boundary

P1-P4 are non-live foundation work. Synthetic/replay tests must cover stale/placeholder Weekly values, successful-fetch/no-write, reset delayed propagation, rolling quota edges, unknown remove/invite effects, typed JSON/null/absence distinctions, and recursive sanitization. No real reset credit, member removal, invite, join, OAuth enrollment, paid-seat change, or threshold-discovery churn is authorized by those epics.

After fan-in, the controller and UI are separate later work. A final real member-change qualification is **at most one** legitimate operational replacement. A reset-credit qualification is separate: if redeeming a legitimate credit restores Weekly usage, the test ends without forcing a member replacement. Response-capture failure is not a reason to retry a remove or invite.

## G2 integration boundary

G2 combines the durable P5 controller, the P6 operator/read model, and the P7 qualification/release tooling while keeping automatic external dispatch disconnected. The P6 enable/disable control remains intent-only and defaults off; reading or toggling the operator surface does not invoke the controller. This is deliberate rather than an implicit feature omission: the current Companion 2.11.47 candidate is qualified as a reproducible P4 artifact, but the running server has no authoritative runtime source that proves the actually installed Companion binary/version matches that P4 tuple. Constructing the expected tuple from constants would be self-attestation and must not grant membership-effect authority.

Before automatic scheduling can be enabled, the release stage must deploy or otherwise establish the exact qualified P4 Companion, verify its binary/provenance outside the membership effect path, and provide that verified runtime attestation to the backend scheduler/controller boundary. Only then may a default-off server-owned scheduler consume enabled workspace intent and invoke the P5 controller. The old file-backed rotation event queue is not effect authority and must not be wired directly to remove/invite: every scheduler attempt still has to reacquire fresh P1 Weekly evidence, P2 reset resolution, P3 quota admission, exact current membership, final Usage retention, and current P4 provenance.

## Q2 shared-schema closure

The production Stable/Beta pair shares PostgreSQL while Stable remains the pristine upstream release. The rotation
quota/history/operator tables are therefore Beta-local extension tables, not official Alembic revisions. On the
beta.9 integration baseline the official shared head is `20260913_000000_add_oidc_provider_flow`; Beta startup never
stamps or upgrades the shared database to a rotation-only head. Operations provisioning must create all four rotation
extension tables atomically, without changing `alembic_version`, and validate their exact PostgreSQL
column/default/constraint/index contract.

The Beta runtime treats the extensions as required: with PostgreSQL it fails before readiness if any required local
extension is absent or physically drifted. Generic Alembic drift ignores local-extension ownership only so upstream
history stays authoritative; that exclusion is not permission to run without the separate extension gate.

Release qualification distinguishes the non-rolling migration epochs. Migration, operation, feature-OFF, and matched
beta.9 runtime evidence bind to the admitted post-migration PostgreSQL identity at
`20260913_000000_add_oidc_provider_flow`. That post-migration epoch also records read-only migration-state probes from
the exact beta.7 Stable/Q2-Beta predecessors proving the DB is ahead/unknown and therefore incompatible. Rollback instead
binds a verified catalog-preserving physical PostgreSQL backup captured at
`20260910_000000_request_logs_missing_cost_index`, including its verified backup manifest digest and source system
identifier. An isolated restore must preserve that system identifier and the predecessor catalog representation used by
the strict Q2 local-extension verifier, reproduce the six local-extension tables using exact per-table count/data
fingerprints, and bind the sealed source snapshot itself to the verified backup digest. A logical `pg_dump`/`pg_restore`
alone is not rollback authority when it rewrites `pg_get_constraintdef()` representation. The physical restore recovers
the three legacy dashboard credential columns with the retired-credential sentinel absent, and only then starts the exact
predecessor image/source/role builds with startup migrations disabled.
Each predecessor container must have a `StartedAt` strictly later than the restored DB epoch and prove it stays running,
reaches `/health/ready`, and reports compatible predecessor-head migration state on that restored DB.
Rollback is a database restore plus predecessor restart, not a beta.9 Alembic downgrade and not an attempt to run
beta.7 code on the beta.9 schema.

The beta.9 Q2 candidate also uses a new first-start gate namespace. Admission binds the final immutable image digest to
its exact source/tree provenance and original entrypoint bytes at runtime; it does not hard-code the final image digest
into source. The old Q2 `592ace...` sentinel is never reused. Publication is atomic/no-overwrite, restart remains `no`
while gated, release preserves the PID1 starttime and network namespace, ambiguous publication fails closed, and any
reviewed post-stop revocation must prove the candidate stopped and the revocation view shares the same runtime mount.
