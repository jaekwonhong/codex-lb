## ADDED Requirements

### Requirement: Recipient action validates its own identity
A managed recipient action SHALL verify the HTTPS ChatGPT origin and the exact recipient email and user ID within the browser-side action before personal-switch effects or invitation acceptance. An earlier successful identity probe SHALL NOT substitute for action-time verification.

#### Scenario: Identity changes between preparation and action
- **WHEN** the action reads the expected email with a different user ID
- **THEN** the action is rejected before any click or acceptance POST

### Requirement: Acceptance evidence distinguishes pre-effect and uncertain outcomes
A failure before the acceptance request SHALL NOT be reported as transport acknowledged. An acceptance network error, HTTP 408 or 5xx response SHALL remain outcome unknown and SHALL NOT cause automatic acceptance replay.

#### Scenario: Session lacks current account before acceptance
- **WHEN** no source account can be obtained before POST
- **THEN** the result is an unacknowledged session failure

#### Scenario: Acceptance returns server error
- **WHEN** the acceptance request returns HTTP 503
- **THEN** the result remains outcome unknown with at most one POST

### Requirement: Missing collection is not absence
Owner, recipient, member OAuth and OAuth-only Task Space acquisition SHALL require a valid collection observation before inferring absence and SHALL NOT create a new Space from a missing or malformed taskSpaces field.

#### Scenario: Malformed initial list response
- **WHEN** taskSpaces is missing or not an array
- **THEN** acquisition stops with an unknown observation and zero creation or membership effects
