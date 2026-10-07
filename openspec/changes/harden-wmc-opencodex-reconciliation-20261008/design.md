# Design

## Stable exact-account read

For one durable `opencodex_account_id`, WMC reads the OpenCodex Controller
projection twice in sequence. The two projections are considered one stable
reconciliation point only when all of the following match:

- exact `account_id`;
- `credential_generation` for pool accounts;
- `main_identity_generation` for `__main__`;
- opaque deterministic `state_revision`.

`observed_at` is intentionally not required to match because OpenCodex captures
the projection again on each read while keeping `stateRevision` deterministic
for unchanged account state.

The second projection is the accepted projection. It must satisfy the existing
30-second account-state freshness bound. A revision/generation race fails closed
and requires a later evaluation; it is not resolved by choosing one side.

## Readiness semantics

Standalone readiness proves that every retained exact binding still resolves to
one fresh, stable OpenCodex account identity. It does not decide whether that
account should receive inference traffic. Therefore `selection_state=excluded`,
`paused=true`, `needs_reauth=true`, `quota_state=exhausted` and
`quota_state=unknown` do not by themselves make the binding invalid.

## Rotation semantics

Quota-driven rotation performs the stable read before reserving Controller-owned
membership mutation budget. Normalized quota, selection and reset-credit rules
remain unchanged and are evaluated from the accepted second projection.

The pre-effect revalidation fence also performs a stable read and then requires
the accepted generation/revision to match the immutable evidence recorded at
admission. A transition observed during either pair prevents the external
membership effect.

## Failure mapping

- transport/auth/schema/exact-identity failure: existing account-state
  unavailable/error behavior;
- two-read generation/revision disagreement: explicit unstable failure;
- accepted second projection older than the freshness bound: existing stale
  failure;
- quota unknown/stale: existing quota-dependent fail-closed behavior.

No failure causes WMC to substitute another OpenCodex account.
