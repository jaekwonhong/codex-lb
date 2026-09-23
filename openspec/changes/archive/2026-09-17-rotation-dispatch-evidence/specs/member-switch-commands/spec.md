## ADDED Requirements

### Requirement: Weekly evidence remains valid at automatic dispatch

The automatic controller SHALL reassess the same decision Weekly evidence with
the current clock after asynchronous admission and quota-accounting work and
immediately before invoking Companion start. The evidence SHALL still be fresh,
exhausted, and before its reset deadline for the exact evaluated member.
Expired or otherwise unknown evidence SHALL prevent Companion start and use the
existing authoritative local non-effect cleanup. It SHALL NOT trigger an
automatic retry or overwrite retained historical snapshots.

#### Scenario: Admission waits beyond the freshness horizon
- **GIVEN** fresh exhausted Weekly evidence admitted an automatic evaluation
- **WHEN** asynchronous start preparation reaches the freshness horizon
- **THEN** the controller does not invoke Companion start
- **AND** the child scope closes and its proven non-effect quota is released

#### Scenario: Reset deadline passes during quota accounting
- **GIVEN** the decision evidence is still within the freshness horizon
- **WHEN** its Weekly reset deadline passes during the final quota write
- **THEN** the controller does not invoke Companion start
- **AND** restarting the controller does not dispatch the rejected operation

#### Scenario: Evidence is still valid after preparation
- **GIVEN** the final decision evidence remains fresh and exhausted
- **AND** its reset deadline has not passed
- **WHEN** all existing identity, provenance, snapshot, and quota gates pass
- **THEN** the existing durable child may issue its single Companion start

### Requirement: Outgoing identity is not removal confirmation

The controller SHALL require exact outgoing email/user identity and the qualified
Companion's durable `verifying_removal` / `outgoing_workspace_absence_observed`
trace before promoting an unknown removal effect to confirmed. The trace entry
SHALL be an operation-stage observation, without action/status command fields.
Removal intent, generic failure, invitation transmission, and missing or
truncated evidence SHALL NOT be substituted for this confirmation. Unknown
effects SHALL remain reserved beyond the rolling quota windows until resolved.

#### Scenario: Removing operation already names the outgoing member
- **GIVEN** a running or failed operation includes the exact outgoing identity
- **AND** it has no authoritative outgoing-absence observation
- **WHEN** the controller reconciles it, including after eight days
- **THEN** removal remains unknown and occupies the local quota
- **AND** no remove request is replayed

#### Scenario: Authoritative outgoing absence is retained
- **GIVEN** the operation identifies the exact outgoing member
- **AND** its durable trace records successful outgoing-workspace absence observation
- **WHEN** the controller reconciles the operation
- **THEN** removal is recorded as confirmed independently of invitation completion
