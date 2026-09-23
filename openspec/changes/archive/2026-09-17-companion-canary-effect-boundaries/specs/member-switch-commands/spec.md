## ADDED Requirements

### Requirement: Canary is one durable workflow

A start request MAY explicitly select canary execution and SHALL default to
ordinary manual behavior when omitted. A canary SHALL require a durable client
flow receipt. At most one canary client flow SHALL bind in the retained operation
store. Its binding SHALL survive completion, release and process reconstruction.
Duplicate starts SHALL only return the existing receipt, never launch work again.
Changing canary mode on an existing client flow SHALL be rejected.
Canary transport SHALL use a dedicated `/canary-operations` endpoint with the
existing managed-write protocol. A rejected/unsupported canary endpoint SHALL
NOT fall back to ordinary `/operations`; each endpoint SHALL reject a mismatched
body mode. An older Companion must reject, rather than ignore, the canary mode.
The first canary binding SHALL advance the local receipt schema so an older
runtime cannot read, rewrite, and silently discard the spent canary budget.

#### Scenario: A different canary is requested after release
- **GIVEN** a canary client flow is durably recorded and released
- **WHEN** another client flow requests canary mode
- **THEN** it is rejected before membership work is scheduled

#### Scenario: Old Companion receives a canary request
- **WHEN** the dedicated canary endpoint is unavailable
- **THEN** the backend does not retry on the ordinary operations endpoint
- **AND** no unguarded replacement is started

### Requirement: Canary claims precede each real membership effect

The Companion SHALL persist at most one remove claim and at most one invite claim
for its bound canary before calling the corresponding browser mutation. Failed
or ambiguous effects SHALL NOT refund claims. Invite admission SHALL require a
remove claim and authoritative removal plus outgoing-workspace absence
verification for the same operation. A persistence error, missing receipt, or
duplicate claim SHALL fail closed before that mutation. Restart SHALL not resume
an interrupted canary or grant another claim. No in-memory-only canary is allowed.
Canary removal verification SHALL NOT retry DELETE, including a definitive
`404/member_identity_missing` response that permits retry in manual mode.

#### Scenario: Delete response is lost
- **GIVEN** the remove claim was committed before DELETE
- **WHEN** its response is lost and the service restarts
- **THEN** DELETE is not replayed
- **AND** invite remains blocked unless authoritative outgoing absence was recorded

#### Scenario: Invitation persistence fails
- **GIVEN** removal and outgoing absence have been confirmed
- **WHEN** saving the invite claim fails
- **THEN** the invite browser call is not executed

#### Scenario: Delete reports a missing identity while the member remains visible
- **WHEN** a canary DELETE returns `404/member_identity_missing`
- **AND** inspection still observes the outgoing member
- **THEN** verification fails without another DELETE or an invitation

### Requirement: Managed removal preserves typed telemetry

The managed operation SHALL normalize and durably retain the delete response with
the existing bounded recursive sanitizer, preserving primitive types, absence,
null and capture uncertainty. Subsequent operation updates SHALL retain that
observation. The backend SHALL project it separately from invitation evidence.
Capture failure SHALL NOT create replay authority.

#### Scenario: Later invitation update follows a delete response
- **GIVEN** a managed delete returned sanitized response telemetry
- **WHEN** invitation progress and process reconstruction occur
- **THEN** the same remove observation remains available separately from invite telemetry
