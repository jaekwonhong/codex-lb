## MODIFIED Requirements

### Requirement: Account-state decisions are freshness and generation fenced

The OpenCodex adapter SHALL return an exact-account state projection with
capture time, normalized selection/quota/health state, an opaque state revision,
and the live credential generation for pool credential-scoped evidence or
native-main identity generation for main-account evidence. Before standalone
readiness accepts a retained account binding, and before quota-driven rotation
reserves membership mutation budget, the Controller SHALL obtain two consecutive
projections for the same exact account and SHALL require the applicable
generation and `stateRevision` to remain identical. The second projection SHALL
satisfy the Controller's 30-second account-state freshness bound.

A retained binding SHALL NOT be invalidated merely because the stable account is
paused, requires reauthentication, is quota exhausted, or is otherwise excluded
from inference selection. Those are OpenCodex-owned runtime states interpreted
by rotation policy, not durable binding identity. Quota-dependent decisions
SHALL additionally reject unknown or insufficiently fresh quota evidence. A
generation or relevant state-revision change SHALL require later re-read and
re-evaluation rather than choosing one raced projection.

#### Scenario: Two exact reads race with an account-state transition

- **GIVEN** a workspace member is durably bound to OpenCodex account A
- **WHEN** two adjacent exact-account reads for A return different credential
  generation, main identity generation, or `stateRevision`
- **THEN** WMC fails the reconciliation/evaluation closed as unstable
- **AND** it does not substitute another account or reserve membership mutation
  budget from either raced projection.

#### Scenario: Stable retained binding is excluded from inference selection

- **GIVEN** the exact account id and generation/revision are stable and fresh
- **AND** OpenCodex currently reports the account paused, reauth-required,
  quota-exhausted, or otherwise `excluded`
- **WHEN** standalone WMC validates its retained binding set
- **THEN** the binding remains readiness-valid as an exact identity
- **AND** WMC does not reinterpret that state as permission to route inference
  or silently remap the binding.

#### Scenario: Credential refresh advances generation before mutation

- **GIVEN** a membership replacement was evaluated against account generation N
- **WHEN** OpenCodex advances that account to generation N+1 before the
  account-sensitive command or membership effect
- **THEN** the Controller does not use generation N evidence to authorize the
  action
- **AND** it obtains a fresh stable exact-account projection and re-evaluates
  the affected preconditions
- **AND** the durable member-to-account binding is not remapped merely because
  the credential generation changed.
