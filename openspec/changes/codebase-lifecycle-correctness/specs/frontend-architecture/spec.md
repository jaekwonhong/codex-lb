## ADDED Requirements

### Requirement: An enrollment may continue its exact durable auth child

An owning OAuth enrollment SHALL be able to advance its exact previously
persisted handoff after that child's command has completed. New or unrelated work
SHALL remain blocked until the enrollment is explicitly finalized. Pending,
orphaned or mismatched children SHALL remain blockers.

#### Scenario: Auth command completed while authorization is pending
- **WHEN** an active enrollment owns the exact non-pending handoff for its identity
- **THEN** its explicit advance command may check that authorization
- **AND** no other enrollment or member switch acquires its scope

#### Scenario: Child command outcome is unknown
- **WHEN** the enrollment's handoff still has a pending command
- **THEN** ordinary advance remains blocked
- **AND** only existing exact-receipt reconciliation may resolve it

### Requirement: Ordinary OAuth responses belong to their issuing UI lifecycle

OAuth start, status and completion responses SHALL only change the lifecycle
which issued them. Reset, replacement and unmount SHALL invalidate prior local
consumers without claiming server cancellation. Status polling SHALL have at
most one in-flight request per lifecycle.

#### Scenario: Previous status response arrives during a new flow
- **WHEN** flow A status resolves after the UI has moved to flow B
- **THEN** it cannot complete flow B, replace B's display or stop B's timers

#### Scenario: Start response arrives after closing the UI
- **WHEN** an outstanding start resolves after reset or unmount
- **THEN** it does not resurrect the old display, start polling or issue completion

#### Scenario: Poll interval expires during an outstanding poll
- **WHEN** a status request is already pending for the current lifecycle
- **THEN** the next poll does not send a duplicate request
