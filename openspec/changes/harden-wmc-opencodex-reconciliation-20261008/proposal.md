# Harden WMC/OpenCodex reconciliation

## Why

The extracted Workspace Member Controller already consumes OpenCodex's exact
`controller-account-state` projection and fences quota-driven mutation evidence
by account generation and `stateRevision`. The standalone readiness path,
however, currently accepts a single exact-account read as sufficient evidence
that a retained binding is usable. A projection can change between two adjacent
Controller reads while still being individually schema-valid, so a single read
does not prove a stable reconciliation point.

The long-term authority split must remain unchanged: WMC owns workspace
membership and OpenCodex owns credentials, pool eligibility, quota, cooldown,
request failover and thread/account affinity. This change only strengthens the
read fence between those authorities.

## What changes

- Require two consecutive exact-account projections with the same account
  generation namespace and `stateRevision` before standalone readiness treats a
  bound account as reconciled.
- Require the accepted projection to be fresh under the existing 30-second
  account-state policy.
- Apply the same stable-read fence before quota-driven rotation reserves
  membership mutation budget, and again when account evidence is revalidated
  before an external membership effect.
- Do **not** require a retained binding to be OpenCodex-selectable during
  readiness. Paused, reauth-required, quota-exhausted or otherwise excluded
  accounts remain valid durable bindings; those states are interpreted only by
  rotation policy.
- Keep quota classification and routing eligibility authoritative in OpenCodex.
  WMC does not reconstruct them from raw percentages.

## Scope exclusions

- No live workspace membership mutation.
- No OpenCodex account pause/resume, reauth, quota refresh or reset-credit
  mutation.
- No inference routing changes.
- No new public WMC mutation endpoint.
