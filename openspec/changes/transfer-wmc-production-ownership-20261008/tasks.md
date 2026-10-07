# Tasks

## Implementation

- [x] Add mutation-enabled standalone WMC configuration, writable-DB readiness
  validation, production switch effect adapter, and authenticated mutation API.
- [x] Add Codex-LB legacy writer fencing for member-switch creation/commands,
  rotation-intent writes, and the legacy rotation scheduler.
- [x] Preserve legacy read/status and OAuth-enrollment surfaces for staged
  rollback/4.5 migration.

## Verification and cutover

- [x] Add focused tests for production effect protocol, auth/action gating,
  writable/read-only startup, legacy writer fencing and scheduler disablement.
- [x] Run WMC/member-switch regression and static/OpenSpec gates.
- [x] Create a dedicated WMC database writer principal with least-required table
  privileges and retain the previous read-only deployment for rollback.
- [x] Promote mutation-enabled WMC without executing a membership effect; prove
  live readiness and retained two-binding validation.
- [x] Fence legacy Stable/Beta writers in a quiescent window and retain their
  previous containers/images for rollback.
- [x] Verify WMC is the only enabled production membership writer while
  OpenCodex remains the inference/account-pool authority.
