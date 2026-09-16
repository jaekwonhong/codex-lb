# G1 — Foundation Integration Handoff

## Integrated source

G1 fans the three Python/Beta foundation epics into one source line from the S1
contract commit `08458354efe5ea27f24de76b7fa06bba1f6bd1ed`:

- P1 Weekly Usage Observation: `b35de7e2a1416e0f208ed68d3d132dc1ec2bac83`
- P2 Reset Credit Resolution: `cf4f6e59ff01410943042e2d363adfd9943ffbc1`
- P3 Quota / History / Retention: `f193e84be29a705c6e828220356e24b5396c24f7`

G1 adds only composition glue and synthetic qualification. Its public foundation
boundary ends at `admission_ready`; it does not dispatch member remove, invite,
join, OAuth, reset-credit, or deployment effects.

## Usage / Reset / Quota boundary for P5

`app.modules.member_switch.rotation_foundation` is the composition boundary.

- `RotationEvaluationIdentity` binds one evaluation id, workspace id, exact
  account/member identity, and stable reset `redeem_request_id`. Weekly, Reset,
  and Quota evidence must carry the same evaluation identity; mixed evidence is
  `invalid_evidence` and cannot become admission-ready.
- `UsageUpdater.force_rotation_usage_observation()` performs one actual Usage
  fetch and returns exact-member provenance plus same-response classified 5H and
  Weekly windows. Stored Usage rows are not a substitute for this receipt.
- `RotationWeeklyEvidence` retains that immutable P1 Weekly observation rather
  than caching an earlier assessment. Quota reservation and final foundation
  evaluation both require a freshly resolved current member and decision-time
  `now`, then rerun P1 freshness, reset-expiry, identity, and boundary checks.
  Evidence that was valid moments earlier can therefore become `usage_unknown`
  before admission if its reset or freshness window has elapsed.
- `build_weekly_recovery_observer()` adapts each fresh P1 receipt to P2's
  `WeeklyRecoveryState` and re-resolves the current member before accepting the
  observation. The caller supplies a post-effect `not_before` boundary.
- `resolve_rotation_reset_credit()` remains P2's only reset-resolution entry
  point. Its result carries the local account id and workspace-account id, and
  G1 requires those plus the stable `redeem_request_id` to match the evaluation
  before Reset evidence can be composed. `USAGE_RECOVERED` blocks replacement,
  and `RECONCILIATION_PENDING` or `UNAVAILABLE` is an attention state rather than
  permission to continue.
- `reserve_rotation_quota()` accepts the bound Weekly/Reset evidence and creates
  a P3 reservation only when the same evaluation is still fresh-exhausted with
  authoritative `CONFIRMED_NO_REDEEMABLE_CREDIT`; pending/unavailable Reset
  evidence cannot consume a quota slot. The reservation decision retains its
  stable operation id and exact evaluation identity. The P3 repository must
  receive its own short-lived database session because it owns commit/lock
  boundaries internally. An unknown remove/invite effect cannot be marked
  completed and remains conservatively counted even if a legacy row already
  contains a completion timestamp. Confirmed operations age from their actual
  confirmed effect timestamp rather than from an earlier reservation timestamp;
  malformed confirmed rows with missing or inconsistent effect-time provenance
  remain conservatively held.
- `evaluate_rotation_foundation()` reaches `ADMISSION_READY` only from a fresh
  exhausted Weekly assessment, authoritative `CONFIRMED_NO_REDEEMABLE_CREDIT`,
  and an admitted P3 reservation. No external effect exists in this function.
- `final_usage_snapshot_inputs()` converts one exact same-fetch 5H+Weekly P1
  receipt into P3 immutable retention inputs. Each input carries the source
  workspace/account/member identity as well as fetch provenance, and the P3
  repository cross-checks that source identity against the identity being
  persisted before commit. Missing, stale, mismatched, or incomplete evidence
  fails closed before a membership mutation can be admitted.

P5 must keep the existing durable member-switch `claim -> execute` authority as
the execute-once gate for remove/invite/OAuth effects. P3
`record_effect_request()` is durable effect accounting, not an execute-once
claim. P5 must also persist reset-resolution/evaluation state independently of
the reset-credit request pin lifetime so a resumed evaluation cannot consume a
second credit after the central pin expires.

## Read model / status boundary for P6

`RotationFoundationReadModel` exposes the foundation status without exposing an
effect executor. Its states distinguish:

- Usage unknown vs available vs confirmed exhausted requiring reset resolution;
- reset recovered, reset reconciliation pending, and reset unavailable;
- quota required, quota blocked, and admission ready;
- inconsistent evidence, which fails closed as `invalid_evidence`.

The read model includes Weekly reason, reset status, quota code, and rolling
24H/168H counts. P6 can project these fields into UI/API status without deriving
permission from rounded display Usage or from Companion telemetry.

## Failure boundary for P7

G1 contains no automatic effect dispatch and no live feature enablement. P7
should treat `admission_ready` as the final G1 boundary and verify that all
unknown/stale/reset-pending/quota-blocked states remain unable to cross into the
existing durable mutation authority. Unknown remove/invite effects continue to
hold P3 quota until authoritative non-effect evidence permits release.

## P4 Companion dependency and provenance

P4 remains a separate Companion/operations artifact and is not cherry-picked
into this Python source line.

- P4 ops branch commit: `47ac829a23b9811537bcd2d21ae9b8003c9c464a`
- frozen ops source: `97becd4b66a5569efd3895d10ff7c9beec3eea97`
- frozen Beta integration: `ace3be6125969e02a4c0d6b284f236a31914c814`
- exact live Companion binary SHA-256:
  `9e74d21f5bd912327d674e4704d8a4a9e01c038d7983128993d89238c2057228`
- candidate version: `2.11.47`
- candidate binary SHA-256:
  `0f7b665e47f1b2cd4959814afe3ee68fe0aa5cc25a264e295997d3499290f1ce`
- artifact: `overlays/member-rotation-typed-telemetry-20260913/companion.patch.gz`
- artifact SHA-256:
  `eb8cb39de01e2b92c834f16bab571e8e3c1420d507113a146dd47da674e9f9fc`
- decompressed patch SHA-256:
  `b4a4dca639f63870bd6800835905b8c5a68a5c54dc83d3a4d410e651bc7a48da`
- source reconstruction: `EXACT_SOURCE_MATCH`
- patch replay: `P4_PATCH_REPLAY_EXACT`

P4 distinguishes `remove_response` and `invite_response`, typed JSON primitive
fields including explicit null and absence, and the capture states `json`,
`empty_body`, `json_parse_failure`, `response_not_received`,
`transport_failure`, `body_read_failure`, `sanitization_failure`, and
`capture_failure`. Its qualified no-replay behavior also keeps invitation issued
separate from final membership confirmation.

There is an explicit P5 contract gap at this G1 HEAD: the current Python
`Operation` / `InvitationSettlement` schemas do not expose P4's typed response
observation fields or `InvitationNonEffectConfirmed`, the Python Companion port
does not expose the typed removal-observation response, and the P4 patch does not
add an advertised catalog capability token that the server can use as proof that
typed telemetry is installed. P5 therefore must add an additive server schema
and an explicit P4 capability/version provenance gate before using the typed
telemetry. Until that boundary is implemented, telemetry failure must remain an
attention condition and must never authorize effect replay.
