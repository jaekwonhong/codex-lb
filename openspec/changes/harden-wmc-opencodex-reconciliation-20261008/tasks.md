# Tasks

## Contract and implementation

- [ ] Add a reusable two-read exact-account stability fence over generation and
  `stateRevision` without interpreting routing eligibility.
- [ ] Apply the fence to standalone bound-account readiness with the existing
  30-second freshness policy.
- [ ] Apply the fence before rotation budget reservation and pre-effect account
  evidence revalidation.
- [ ] Preserve excluded/paused/reauth/exhausted durable bindings as readiness-
  valid when identity, revision and freshness are stable.

## Verification

- [ ] Add regressions for stable, unstable, stale and excluded/paused account
  projections.
- [ ] Run focused WMC adapter/standalone/rotation/mutation tests and static
  checks.
- [ ] Validate the OpenSpec change strictly.
- [ ] Run retained two-binding read-only validation against live OpenCodex 2.80
  without changing live membership or account routing state.
