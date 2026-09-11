## ADDED Requirements

### Requirement: Durable participant command admission
Session preparation, browser opening and browser closing SHALL accept an immutable
command UUID, run UUID, membership operation identity and exact request fingerprint.
Companion SHALL persist pending intent before invoking a driver and completion before
acknowledging it. Exact repeats SHALL return stored receipts without invoking drivers;
changed requests with the same command UUID SHALL be refused. Pending work SHALL
block new participant commands, survive reconstruction and have no automatic expiry.

#### Scenario: Response loss after completion
- **WHEN** a completed command response is lost
- **THEN** read-only lookup returns its original completed receipt
- **AND** neither lookup nor command replay invokes a browser or session driver

#### Scenario: Driver or storage interruption
- **WHEN** a driver outcome or completion publication is uncertain
- **THEN** the persisted command remains pending
- **AND** no new command, restart or timeout discards that intent

### Requirement: Explicit evidence-only reconciliation
The backend SHALL persist the participant request fingerprint before transmission.
Reconciliation SHALL validate command UUID, run UUID, action, membership operation,
full target identity and fingerprint, and SHALL only consume completed receipts.
Missing, pending or mismatched records SHALL NOT authorize a retry or release.
Session preparation SHALL be a separate explicit step from OAuth preparation.

#### Scenario: Session completion reply is lost
- **WHEN** an operator reconciles the exact completed session receipt
- **THEN** only the session-prepared state is restored
- **AND** OAuth preparation still requires a separate explicit command

### Requirement: Completion evidence is not current browser authority
A historical open receipt SHALL preserve its browser operation ID but SHALL NOT
authorize a guessed CDP handle or imply that a browser survived a restart. Commands
requiring a runtime-bound target SHALL refuse a different Companion incarnation.
Finalization SHALL refuse unresolved participant commands and unclosed targets.
GET requests and constructors SHALL NOT resume commands or release ownership.

#### Scenario: Companion restarted after a completed open
- **WHEN** the receipt is reconciled after reconstruction
- **THEN** its recorded browser ID can be displayed
- **AND** closing it requires the original runtime binding, otherwise manual review is required

### Requirement: Receipt admission cannot be bypassed by old browser endpoints
The production browser-open, browser-close and session-readiness legacy endpoints
SHALL refuse direct writes when the durable participant controller is wired.
Capability negotiation SHALL require the matching participant protocol before a
new managed membership operation is admitted.

#### Scenario: An older client calls a raw browser endpoint
- **WHEN** the caller omits durable command admission
- **THEN** the request is refused before clipboard or driver work
