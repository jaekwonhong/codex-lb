# Design

## Cutover order

1. Build and test the mutation-enabled WMC candidate against a writable
   migration database principal.
2. Validate retained two-binding identity/account-state evidence and prove the
   production mutation route is authenticated and no-replay aware without
   executing a real membership effect.
3. Promote WMC first while legacy Codex-LB writers remain available.
4. Recheck that the shared journal has no active/pending operation and automatic
   rotation has no enabled intent/plan.
5. Restart Stable/Beta with
   `CODEX_LB_WORKSPACE_MEMBERSHIP_WRITER=wmc`, which fences legacy mutation
   creation/commands and makes the legacy scheduler inert.
6. Retain pre-cutover WMC, Stable, and Beta containers/images as rollback
   artifacts.

At no point are both writers allowed to own the same new effect. The shared
journal already blocks a competing legacy effect once WMC has claimed one; the
runtime fence removes the remaining legacy creation path after WMC promotion.

## Standalone mutation API

All `/v1` routes continue to use the existing WMC bearer admin dependency.

- `POST /v1/mutations` submits one exact `MembershipMutationCommand`.
- `GET /v1/mutations/{operation_id}` reads retained mutation state.
- `POST /v1/mutations/{operation_id}/reconcile` performs observational
  reconciliation only; it never resends an effect.

The production HTTP route admits only `action=switch`. Unsupported actions fail
before the journal/effect boundary.

## Production Companion adapter

The production adapter reuses the qualified Companion protocol but sends
`StartRequest(canary=false)` to `/operations`. It requires owner observation,
owner mutation, recipient lifecycle, safe managed-remove telemetry, durable
client flow, and durable participant-command capabilities. Canary-only effect,
rollback, epoch and budget gates are deliberately absent.

The adapter preserves the canary adapter's settlement rules: exact outgoing
absence, safe mutation-capture evidence, invitation issuance, final membership
confirmation and finalization are required for `completed`. Ambiguous/failed
external evidence remains `outcome_unknown`; reconciliation uses lookup/status
only and never resends start.

## Writable persistence boundary

`WMC_MUTATIONS_ENABLED=false` remains the default and permits the current
read-only shadow database principal. When enabled, startup checks the live
database transaction is writable before readiness and constructs the existing
legacy journal compatibility adapter over the shared member-switch tables.

The production deployment uses a dedicated WMC writer role with only the table
permissions required for Controller membership state; it does not use the
Codex-LB application credential as a shortcut.

## Legacy fencing

`CODEX_LB_WORKSPACE_MEMBERSHIP_WRITER` defaults to `legacy`. Setting it to `wmc`
does not remove read/status routes. It rejects:

- creating a legacy member-switch run;
- issuing a legacy member-switch run command that can progress membership;
- writing legacy automatic-rotation intent;
- executing any legacy rotation scheduler plan.

OAuth enrollment endpoints remain temporarily available because their inference
credential ownership is retired in task 4.5 rather than silently reimplemented
inside WMC.
