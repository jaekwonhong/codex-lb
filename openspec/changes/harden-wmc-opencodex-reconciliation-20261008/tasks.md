# Tasks

## Contract and implementation

- [x] Add a reusable two-read exact-account stability fence over generation and
  `stateRevision` without interpreting routing eligibility.
- [x] Apply the fence to standalone bound-account readiness with the existing
  30-second freshness policy.
- [x] Apply the fence before rotation budget reservation and pre-effect account
  evidence revalidation.
- [x] Preserve excluded/paused/reauth/exhausted durable bindings as readiness-
  valid when identity, revision and freshness are stable.

## Verification

- [x] Add regressions for stable, unstable, stale and excluded/paused account
  projections.
- [x] Run focused WMC adapter/standalone/rotation/mutation tests and static
  checks.
- [ ] Validate the OpenSpec change strictly.
- [x] Run retained two-binding read-only validation against live OpenCodex 2.80
  without changing live membership or account routing state.
