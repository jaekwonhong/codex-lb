# Workspace Member Controller single-workspace canary runbook

This runbook is for the separately authorized single-workspace membership canary. It is not a production cutover procedure.

## Safety model

The normal canary is split into preflight, forward, and rollback. A forward that fails after real membership effects is handled by the separate partial-recovery path below; normal rollback and partial recovery are mutually exclusive for one parent. No later phase is automatically launched by the forward invocation.

The prepared canary target is `cdp-2`. After repeating read-only selection qualification, the selected target preset is `pool-cfa8753f2d3c4154c2660a0ea4b50f95`. Do not substitute another workspace or target without repeating the read-only selection/preflight qualification.

The canary requires:

- Companion admission `ready`;
- no active Controller/legacy member-switch scope;
- authoritative current membership observation with exactly one known non-owner member;
- exact allowlisted target preset identity;
- explicit exact OpenCodex bindings for both current and target subjects;
- both exact OpenCodex accounts to have usable credentials and remain administratively paused so the membership canary cannot place either account into inference routing;
- the qualified Companion mutation/observation/recipient/canary/telemetry/durable-flow capability set;
- `member_rotation_canary_rollback_binding_v1`, proving the purpose-bound rollback contract and active qualified epoch are present;
- a private absolute handoff state path with owner-only permissions.

The canary effect adapter uses only the dedicated Companion canary endpoint. It never retries a start request and never falls back to the ordinary operation path.

## Preflight

Preflight is read-only and does not require the mutation acknowledgement. It must succeed before the forward phase is considered eligible.

Expected success report includes `ready=true` and `exactAccountBindings=2`. Any missing binding/account, stale/ambiguous workspace observation, active control scope, or non-idle Companion blocks the canary before mutation.

As of the 11-2B qualification step, the current and selected target subjects have been onboarded into the OpenCodex native account pool, explicitly bound, and kept paused for routing isolation.

## Forward phase

The forward phase requires both `--execute` and the exact acknowledgement environment value used by the canary runner. It performs only one current→target canary switch.

A successful forward must prove all of the following before it is accepted:

- durable Controller command/journal claim committed before effect;
- dedicated canary start accepted once;
- exact outgoing identity recorded;
- trace contains `outgoing_workspace_absence_observed`;
- invitation was issued;
- final target membership was confirmed;
- response telemetry contains no unsafe capture state;
- Companion operation finalized/released;
- Controller active scope released;
- authoritative membership observation shows the target as the sole current non-owner member;
- a mode-`0600` canary handoff state file is written for the later rollback turn.

If evidence becomes ambiguous after the effect may have been sent, stop. Do not run another forward command and do not start rollback until the original operation is reconciled.

The q2 forward on 2026-10-07 reached a narrower terminal state than generic ambiguity: outgoing removal was confirmed and the target invite was issued, but target activation could not be confirmed after all bounded automatic/fallback settlement attempts. Its terminal code is `acceptance_settlement_not_observed`. The q2 forward budget is spent and MUST NOT be retried.

## Rollback phase

Rollback is a separate authorization. It reads the retained handoff state and refuses to continue unless the target identity is still current and both exact OpenCodex bindings remain unchanged and usable.

Rollback uses a second dedicated canary operation target→original. Success requires the same evidence gates as the forward phase plus final observation that the original subject is restored, active scope is released, and Companion admission is idle again.

The rollback start is not a generic second canary. It carries `canaryPurpose=rollback` plus the retained forward Controller operation UUID as `canaryParentClientFlowId`. Companion resolves that UUID to the durable forward receipt and admits rollback only when the forward receipt is completed, released, fully claimed/confirmed, and the rollback preview is the exact reverse identity transition. The same parent cannot authorize a second rollback.

The failed q2 forward does **not** satisfy this rollback contract because it is failed/unreleased and target membership was never confirmed. Do not fabricate a rollback handoff for it.

## Partial-effect recovery phase

Partial recovery is a separately qualified purpose, not a new forward budget and not normal rollback. It is eligible only for the exact retained q2 parent that has confirmed outgoing removal, an issued pending target invite, `FinalMembershipConfirmed=false`, and terminal `acceptance_settlement_not_observed`.

Recovery preflight MUST prove the exact retained Controller parent, exact Companion parent client-flow, recovery capability, unchanged catalog/workspace identity, paused/usable exact OpenCodex bindings for original and failed target, and the parent evidence shape. The Companion start gate then freshly requires zero non-owner members and exactly one invite whose email and invite id equal the retained failed-target invitation.

Execution uses a new durable recovery child client-flow. The Controller persists that child id before the recovery endpoint is called. Companion binds the child before browser mutation, claims cleanup before canceling the target invite, proves exact invite absence, then claims restoration before inviting the original member. Success requires completed active original membership, recovery trace `recovery_target_invite_absence_observed`, final restoration settlement, Companion finalize/release of child plus parent, and a fresh authoritative observation of the original member. Only after all of that does WMC persist `phase=recovered` and release its retained scope.

If a prepared child has no observable Companion receipt, do not start it again automatically. If the Companion child is already finalized but WMC completion was lost, a resume may perform only the missing read-only restoration check and Controller completion; it must not replay cleanup or invite effects.

## Routing isolation

The canary deliberately requires both bound OpenCodex pool accounts to remain paused. Membership mutation is executed by the qualified Companion canary path, not by OpenCodex inference routing, so unpausing would add risk without adding evidence. A missing credential or reauthentication-required state still blocks the canary.

## Durable Companion canary/recovery budget

Canary budgets have no expiry or refund. The legacy receipt, q1 forward and q2 forward remain durable evidence. q1 and q2 each admit at most one forward in their qualified binary contract; q2 is already spent. Deleting/restoring the receipt store, changing a client-flow id, restarting, or finalizing a failed operation is not authority to replenish a forward budget.

The q2 partial-effect recovery keeps the receipt store at schema version 3 and adds at most one `purpose=partial_recovery` child to the exact failed q2 parent. Existing receipts retain their canonical operation/canary evidence; the failed parent changes only by becoming released after successful recovery. The older canary.4/q2 binary does not understand the `partial_recovery` receipt shape and rejects the recovered schema-3 store with `canary_store_schema_invalid`, so schema number alone is not evidence that a downgrade is safe.

After successful recovery, keep a canary.5-compatible binary while the recovered receipt store is retained. A post-recovery operational mode may remove `MEMBER_SWITCH_CANARY_QUALIFICATION_EPOCH`; canary.5 can still load the recovered store in that mode, while purpose-bound canary admission is disabled. Do not downgrade to canary.4 merely because the store remains schema version 3.
