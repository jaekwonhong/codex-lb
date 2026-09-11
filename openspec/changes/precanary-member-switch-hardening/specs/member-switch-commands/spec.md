## ADDED Requirements

### Requirement: Deterministic participant rejection has durable evidence
When Companion can reject a participant command before invoking its session or
browser driver, it SHALL persist a completed typed receipt for the exact command
and request fingerprint before returning the rejection. Replaying or looking up
that command SHALL return the receipt without invoking a driver. Uncertain driver
or completion-publication outcomes SHALL remain pending instead.

#### Scenario: Runtime browser binding was lost before close
- **WHEN** an exact close request is rejected before any close driver call
- **THEN** Companion persists a completed no-effect close receipt
- **AND** backend reconciliation can consume that receipt without replaying close

### Requirement: Persisted release intent can be explicitly completed
A membership receipt marked released while its matching flow owner is still
present SHALL be observable as release-pending rather than finalized. An explicit
backend reconciliation of the original pending finish command MAY invoke the local
finalize operation once more only for that exact release-pending operation. No
membership, invitation, browser or OAuth work may be repeated by that operation.

#### Scenario: Companion stopped after release marker publication
- **WHEN** the backend still has the original pending finish and lookup reports the
  exact operation as release-pending
- **THEN** explicit reconcile completes owner release and marks the run completed
- **AND** no membership operation is replayed

### Requirement: Manual frontend has one mutation contract
Production frontend source SHALL use the server-owned run API as the only
member-switch mutation client. Unreferenced legacy direct Companion mutation
clients SHALL NOT remain in the production source tree.

#### Scenario: Static import audit
- **WHEN** production frontend imports are inspected
- **THEN** no direct cleanup, recovery, session-readiness or OAuth-browser member
  switch client is reachable from the application bundle
