## ADDED Requirements

### Requirement: Browser assistance belongs to the current member operation
Production Companion browser assistance SHALL require the exact current member
operation owner before clipboard or browser side effects. A historical completed
membership record alone SHALL NOT authorize a new browser action. A retained
browser belonging to a different operation SHALL NOT be closed or replaced by
an open request.

#### Scenario: An old tab submits a completed historical operation
- **WHEN** another operation owns the workflow, or the old operation was released
- **THEN** open and code-entry requests for the old operation are rejected before driver or clipboard calls
- **AND** the current browser remains unchanged

### Requirement: Unavailable verification pages retain cleanup identity
When a browser driver returns an owned target but cannot display the verification
page, Companion SHALL retain and return its browser operation ID. The parent run
SHALL be able to offer explicit cleanup without repeating membership or treating
the response as a lost operation.

#### Scenario: A created target displays no verification page
- **WHEN** the driver reports verification_page_unavailable with a target handle
- **THEN** the response includes the retained operation ID
- **AND** only explicit close releases that target

### Requirement: Synthetic participant integration verifies production seams
Offline integration SHALL exercise registered routes, request-scoped dependency
wiring, durable admission, real temporary database account operations and actual
Companion response serialization. It SHALL prohibit real HTTP or browser driver
calls and distinguish protocol snapshots from a live cross-host qualification.

#### Scenario: A manual operation completes through synthetic participants
- **WHEN** explicit commands pass through the API and participant adapters
- **THEN** stored-state GET requests perform no participant calls
- **AND** old auth is quarantined before verification, removed only after verified incoming auth, and ownership released only after explicit finish

### Requirement: Browser driver uncertainty is not an authoritative rejection
Companion browser-open responses SHALL explicitly carry outcomeUnknown. Exceptions
across a browser-driver boundary SHALL set that flag rather than claim a no-effect
rejection. Code-entry failure SHALL retain the original target and SHALL NOT
automatically open a replacement. The backend SHALL preserve its pending command
when uncertainty is reported or the required outcome field is absent.

#### Scenario: The driver throws after attempting to create or modify a target
- **WHEN** a browser action does not return a verified result
- **THEN** no automatic second target is opened
- **AND** the parent command remains pending, with no new open command allowed

#### Scenario: An older participant omits outcome metadata
- **WHEN** the browser response has no outcomeUnknown field
- **THEN** response validation fails closed and does not enable a repeat operation
