## ADDED Requirements

### Requirement: Explicit Companion HTTP surface
Companion SHALL admit only tagged stored-read and managed-command endpoints under
the member-switch prefix. Unmarked routes, including browser-backed GET routes,
SHALL be rejected before body parsing or side effects. Managed writes SHALL require
the current protocol marker in addition to existing Host and Origin validation.
The marker is compatibility fencing, not a secret or local-process authentication.

#### Scenario: A stale client calls cleanup or recovery
- **WHEN** a legacy route is called, even with the current protocol marker
- **THEN** the request is rejected without invoking its original handler
- **AND** current flow, browser, catalog and receipt state remain unchanged

#### Scenario: A stale client uses a still-supported command path
- **WHEN** a managed command has a missing or wrong protocol marker
- **THEN** it is rejected before any command or preview is admitted

### Requirement: Retained state blocks implicit migration
Construction and admission reads SHALL NOT rewrite, delete or adopt existing flow
or receipt files. A legacy owner without a matching client-flow receipt and an
unreleased receipt without its owner SHALL block a new membership operation.
Legacy ownership SHALL NOT be released by a bare operation ID.

#### Scenario: Old flow and incomplete participant records are present
- **WHEN** the candidate reconstructs them or reads admission state
- **THEN** their bytes remain unchanged and new work remains blocked
- **AND** only explicit receipt-backed actions on a matching managed run may progress

### Requirement: Backend cutover admission
New runs SHALL record their control protocol. Unversioned in-flight runs SHALL be
observable but SHALL expose no executable actions. New runs and membership start
SHALL be blocked by quarantined outgoing auth or unresolved orphan control records.
Read-only diagnostics SHALL use stored data only and SHALL preserve record IDs.
No automatic migration, forced release, age-based cleanup or token repair is provided.

#### Scenario: Browser storage was cleared but old auth is quarantined
- **WHEN** a new run is requested
- **THEN** the backend rejects it before Companion or OAuth work
- **AND** diagnostics identify the retained account without exposing tokens

### Requirement: Local launcher mutations cannot overlap retained work
HTTP launcher mutations that can change shared profiles SHALL share the managed
admission gate and SHALL be refused while membership or participant work is retained.
Stored diagnostics remain available. This does not fence manual OS actions or
another binary using a different profile, port or database.

#### Scenario: A launcher reset races a managed start
- **WHEN** both HTTP operations reach the admission gate
- **THEN** they do not execute concurrently
- **AND** a reset arriving after membership acquisition is refused
