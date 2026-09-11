## ADDED Requirements

### Requirement: OAuth-only verification uses the managed member's Ego Lite profile

For an OAuth-only enrollment, the system SHALL open the verification page only in
an Ego Lite task space whose profile id is deterministically bound to the managed
account represented by the enrollment identity. It SHALL NOT open the verification
URL in the system default browser or fall back to the legacy CDP browser.

#### Scenario: Exact managed profile is available
- **WHEN** the current enrollment identity resolves to exactly one managed account and its expected Ego profile exists
- **THEN** device-code issuance is admitted, the verification URL is opened in a task space using that exact profile, and the task space is handed to the user with the installed Ego runtime reporting `agentDelegatedToUser`

#### Scenario: Expected profile is missing
- **WHEN** the exact managed account's Ego profile does not exist before device-code preparation
- **THEN** device-code issuance is refused and no URL is opened in any browser or profile

#### Scenario: Profile preflight runtime is unavailable
- **WHEN** the exact profile cannot be checked because the Ego runtime fails or times out
- **THEN** the original runtime failure remains visible, OAuth is not started, and the condition is not misreported as a missing profile

### Requirement: Browser-open authority is bound to durable enrollment identity

The browser-open command SHALL revalidate the enrollment id, preset id, email,
user id, workspace id/account id, and catalog fingerprint before any Ego browser
effect. A retained or repeated command SHALL be reconciled from durable evidence
instead of implicitly opening another task space.

#### Scenario: Catalog or identity changed after device-code preparation
- **WHEN** any authoritative member identity no longer matches the stored enrollment
- **THEN** no Ego task space is created or reused and the command fails closed

#### Scenario: Command response is lost after task-space creation
- **WHEN** the host has durable evidence for the exact browser-open command but the dashboard response was lost
- **THEN** reconciliation returns that evidence without opening a second task space

### Requirement: OAuth browser migration is scoped to OAuth-only enrollment

The Ego Lite integration SHALL NOT replace membership observation, owner browser,
recipient acceptance, or other existing CDP-backed member-switch operations in
this change.

#### Scenario: Existing member-switch path runs
- **WHEN** a non-OAuth-only member-switch browser operation is requested
- **THEN** the existing CDP-backed contract remains unchanged
