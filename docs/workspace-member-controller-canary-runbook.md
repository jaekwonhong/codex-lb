# Workspace Member Controller single-workspace canary runbook

This runbook is for the separately authorized single-workspace membership canary. It is not a production cutover procedure.

## Safety model

The canary is split into three operator-visible steps: preflight, forward, and rollback. Forward and rollback are never executed automatically in the same invocation.

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

## Rollback phase

Rollback is a separate authorization. It reads the retained handoff state and refuses to continue unless the target identity is still current and both exact OpenCodex bindings remain unchanged and usable.

Rollback uses a second dedicated canary operation target→original. Success requires the same evidence gates as the forward phase plus final observation that the original subject is restored, active scope is released, and Companion admission is idle again.

The rollback start is not a generic second canary. It carries `canaryPurpose=rollback` plus the retained forward Controller operation UUID as `canaryParentClientFlowId`. Companion resolves that UUID to the durable forward receipt and admits rollback only when the forward receipt is completed, released, fully claimed/confirmed, and the rollback preview is the exact reverse identity transition. The same parent cannot authorize a second rollback.

## Routing isolation

The canary deliberately requires both bound OpenCodex pool accounts to remain paused. Membership mutation is executed by the qualified Companion canary path, not by OpenCodex inference routing, so unpausing would add risk without adding evidence. A missing credential or reauthentication-required state still blocks the canary.

## Durable Companion canary budget

The deployed Companion is intentionally **one canary workflow for the retained lifetime of its durable receipt store**. The running `FourSessionLauncher` binary has SHA256 `1ec90e2b7315a9a19d718b03ff7c8ec54e90ff72aa9ca92b83a060fe0456b2d1`, matching the preserved `rotation-build-candidate-20260918` package candidate. Its source contract rejects a new canary whenever any retained receipt already carries canary state.

This budget has no expiry or refund. Completion, failure, finalization/release, process restart, or a different client-flow/operation id do not restore it. The retained-store contract also explicitly says that restoring an old store or starting with an empty store is **not** authority to replenish the canary budget. The deployed HTTP surface has no canary reset/re-arm endpoint.

The earlier `cdp-2-thinklet09` canary bound the single durable canary receipt and ended before a membership effect was authorized (`RemoveClaimed=false`, `RemovalConfirmed=false`, `InviteClaimed=false`). That is nevertheless sufficient to consume the workflow budget because the receipt is persisted before membership work is scheduled. The later qualified target therefore fails closed at start with `canary_workflow_budget_spent`; retrying it against the current Companion cannot succeed and must not be attempted.

If another live canary is required, do not delete or rewrite `member-switch.operations.json` and do not route through the ordinary `/operations` endpoint. A new, separately qualified Companion contract/release must explicitly define a new canary qualification epoch (or equivalent operator-authorized budget generation) while retaining prior canary evidence and no-replay guarantees. Only after that candidate is tested, provenance-qualified, deployed, and re-preflighted may another forward canary be authorized.

The qualified `2.11.48-canary.3` candidate uses epoch `wmc-20261007-q1` for one forward plus one purpose-bound rollback tied to that forward. It does not replenish the earlier legacy canary budget and does not grant a free second forward operation.
