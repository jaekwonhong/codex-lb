# 2026-09-17 post-Q2 dispatch review

## Baseline and scope

Source baseline: `4acf0d9fffd99b5c8677dbed5df460c5ef04f7bd`.
The operations workspace has a sealed beta.9 production cutover result at
`artifacts/beta9-production-cutover-4acf0d9f-20260917T024043Z/production-cutover-final.json`.
It records committed deployment, Stable/Beta readiness 200, PostgreSQL healthy,
automatic rotation disabled, zero enabled rows, and zero quota operations.
This follow-up changes source only; it does not deploy or enable rotation.

The old checklist did not reflect the beta.9 independent backend/shared and
frontend/OpenSpec reviews documented in `docs/usage-member-rotation-p7-qualification.md`.
Those reviews reported no blocking findings for the Q2 semantic rebase. They
are not an approval of the unwired Q3 execution path. The new independent
read-only readiness review found the two controller defects below and three
remaining integration gaps. Q3 remains closed.

## Corrected defects

1. Weekly eligibility was assessed before asynchronous catalog, preview,
   admission and accounting. Four synthetic tests reproduced a Companion start
   after the freshness horizon or reset deadline was reached. The controller
   now reassesses the exact decision receipt immediately before and after its
   final quota write in the existing post-claim/pre-Companion hook. If the write
   completed but evidence expired, it records authoritative local non-effect
   before cleanup. No membership request was sent. A crash before cleanup keeps
   the durable claim/reservation for reconciliation rather than granting retry.
2. Companion 2.11.47 sets removed email/user identity before DELETE and retains
   it on generic failures. The controller previously interpreted that identity
   alone as confirmed removal, allowing unresolved effects to age out of quota.
   It now also requires the durable `verifying_removal` /
   `outgoing_workspace_absence_observed` trace produced after both removal and
   outgoing workspace-absence verification. Missing/truncated proof remains
   unknown. Command trace entries do not qualify as operation observations.

For example, an operation still in `removing` after a lost reply remains unknown
and counted in both local quota windows even eight days later. Successful
outgoing absence may confirm removal while a later invitation failure remains
unresolved separately. Historical snapshots and original reset times survive
both paths.

## Validation

- Baseline qualification: 308 passed; Ruff, ty, original change validation pass.
- Freshness regression before repair: 4 failed, each showing one forbidden start.
- Removal regressions before repair: 5 failed / 2 passed.
- Corrected controller suite: 43 passed.
- Corrected full rotation qualification: 319 passed; Ruff and ty pass.
- Strict OpenSpec validation passes for the follow-up change and, after archive
  and spec synchronization, all 66 specifications.
- Independent patch review: PASS, no blocking findings; reviewer reran all
  11 new regression cases successfully. The review covers these two fixes,
  not Q3 enablement or the remaining Companion integration work.
- The existing Starlette/AnyIO deprecation warning is unrelated to these changes.
- Frozen Companion host verification at `2026-09-17T03:46:04.703936+00:00` passed:
  version 2.11.47, running executable SHA-256
  `0f7b665e47f1b2cd4959814afe3ee68fe0aa5cc25a264e295997d3499290f1ce`,
  matching LaunchAgent program/process inode. This is a point-in-time
  observation, never a reusable dispatch authorization.

The patch does not rewrite previously persisted false-confirmed operations.
The production baseline has zero quota operations and no wired scheduler, so
no corrective data migration is warranted from the available evidence. A
different runtime containing prior controller operations requires separate
reconciliation before activation. The backend freshness check also does not
replace checks at the Companion's later actual DELETE boundary.

## Remaining Q3 integration work

1. Supply current host-verified Companion provenance through a trusted backend
   provider. The expected tuple and a historical JSON report alone are not
   current runtime authority.
2. Add a durable single-workflow canary gate at both actual Companion effect
   boundaries. P7's pure `authorize_canary_effect` currently serves only CLI/tests;
   Python's one `/operations` start launches both DELETE and invite internally.
   A start-only wrapper cannot gate invitation after removal reconciliation.
3. Carry the managed operation's typed remove response into durable operation
   state and the Python read model. The qualified source currently normalizes
   remove telemetry on the separate remove-observation endpoint, while the
   managed flow passes DeleteAsync's result to verification without retaining
   that envelope. `RotationControllerState.remove_response_observation` is
   therefore unpopulated on this flow.
4. Only then connect the server scheduler to current enabled intent, fresh P1
   evidence, authoritative P2 reset resolution, P3 quota and the durable P5
   controller. Requalify any changed Companion identity as a matched candidate.
5. Run at most one legitimate canary when all gates pass. A reset-recovered
   member must not be removed merely to complete qualification.

The remaining work is explicit implementation scope, not a request to enable
the existing OFF runtime. This change is retained for review/release integration;
neither Q3 nor Q4 is marked complete.
