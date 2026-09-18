## ADDED Requirements

### Requirement: Stored observation does not advance operations
Member-switch run-status and auth-handoff-status GET endpoints SHALL return stored state only. They
SHALL NOT invoke OAuth, Chrome, membership mutation, token deletion or reissue.
Progression SHALL require an explicit write-authorized command.

#### Scenario: OAuth completion exists upstream
- **WHEN** the stored handoff is read repeatedly
- **THEN** no upstream status request or account mutation is made
- **AND** an explicit advance command is required to apply completion

### Requirement: Durable command ownership
The backend SHALL own the run identity, revision and transition state in the
application database. It SHALL record intent before an external effect, reject
conflicting concurrent commands, and preserve unresolved outcomes across restart.
Expiration, missing replies and browser storage loss SHALL NOT release ownership.

#### Scenario: Response is lost after a command
- **WHEN** a browser restores a run by its immutable ID
- **THEN** it can read the server record without replaying the command
- **AND** an unresolved effect remains blocked until authoritative evidence resolves it

### Requirement: Explicit small manual state machine
The server SHALL expose bounded phases and permitted next actions. A member
registration success SHALL NOT be represented as completed auth handoff.
The frontend SHALL NOT authorize transitions from a local cached phase.
Preparing auth SHALL quarantine the outgoing auth rather than delete it before
the incoming auth is verified. A fresh recovery request SHALL NOT silently
supersede an unresolved handoff.
Account-row mutations performed from an observed handoff snapshot SHALL remain
conditional on that exact snapshot. Quarantine and unpause writes MUST use a
compare-and-set over the observed status/reason/reset/block/credential material,
and cleanup deletion MUST verify that the quarantined row still has the observed
status, quarantine reason, and refresh-token material immediately before deletion.
A concurrent reauthentication/import or permanent auth transition therefore
supersedes the stale handoff mutation instead of being overwritten or deleted.

#### Scenario: Two browsers attempt the same transition
- **WHEN** both submit commands for one revision
- **THEN** at most one command crosses an external mutation boundary
- **AND** the other observes a conflict or a stored receipt

#### Scenario: Concurrent auth repair supersedes stale handoff cleanup
- **GIVEN** a handoff observed an outgoing row as quarantined under credential A
- **AND** another actor reauthenticates that same local row to credential B before cleanup deletion
- **WHEN** the handoff tries to delete the old auth using its retained snapshot
- **THEN** the guarded delete does not remove credential B
- **AND** the handoff remains failed or attention-required rather than claiming cleanup completed

#### Scenario: Concurrent permanent failure supersedes stale unpause
- **GIVEN** reconciliation observed the exact target row as handoff-quarantined
- **AND** the row becomes `reauth_required` before the unpause write lands
- **WHEN** reconciliation tries to restore it to active
- **THEN** the compare-and-set misses and the `reauth_required` state remains authoritative

### Requirement: Companion durable identity and separated responsibilities
Companion SHALL retain client-flow identity and operation receipts before external
work. A read-only lookup SHALL recover a receipt without membership mutation.
Pure membership decisions SHALL be separable from browser I/O and persistence.

#### Scenario: Companion restarts during membership work
- **WHEN** a retained client flow is looked up after reconstruction
- **THEN** its identity is retained and an unresolved operation is not replayed
- **AND** a conflicting preview for that ID is rejected

### Requirement: Automation qualification
Automation SHALL NOT be reintroduced on page load, focus or network recovery.
Any future worker SHALL use the same durable command admission as manual work.
Unmet recovery or compatibility gates SHALL leave automatic mutation disabled.

#### Scenario: An unresolved manual operation exists
- **WHEN** an automatic candidate would otherwise be eligible
- **THEN** no new membership or OAuth mutation is admitted

### Requirement: Receipt publication preserves the committed identity
Each compare-and-swap write SHALL return its own committed revision, not a later
writer's revision. Companion finalization SHALL persist its release receipt before
freeing ownership and SHALL NOT report completion while that owner remains active.

#### Scenario: A second writer commits before the first response returns
- **WHEN** the first write has committed and another command changes the record
- **THEN** the first caller receives only its own write snapshot
- **AND** it cannot adopt the second writer's revision as its own authority

#### Scenario: Finalization is interrupted between participant state files
- **WHEN** Companion has persisted a release receipt but still owns the operation
- **THEN** reconstruction reports the operation retained, not finalized
- **AND** receipt-write failure prevents ownership release

### Requirement: Incomplete authentication can close its owned browser explicitly
An operator SHALL be able to close the recorded authentication browser without
declaring authentication or the overall run complete. When a device code is
reissued, the UI SHALL explain that the old browser must be closed and reopened.

#### Scenario: Device code changes while its old browser is open
- **WHEN** an explicit auth command records a new OAuth flow
- **THEN** close and subsequent reopen remain explicit actions
- **AND** no membership request is repeated and no ownership is released

#### Scenario: Consecutive commands need separate confirmation
- **WHEN** a confirmation is reopened after the previous command completes
- **THEN** the dialog remains above its overlay and its controls remain clickable
- **AND** each mutation still requires its own explicit confirmation

### Requirement: Failed membership is not proof of an absent effect
A failed admitted membership operation SHALL require attention unless authoritative
evidence proves a safe terminal result. Incoming-auth verification SHALL reject
partial identity collisions before deleting quarantined outgoing auth.

#### Scenario: Membership reports failure after an uncertain invitation
- **WHEN** the admitted operation reports a failure
- **THEN** the run retains ownership and does not offer completion as a reset
