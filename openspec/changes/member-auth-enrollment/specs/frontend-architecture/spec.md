## ADDED Requirements

### Requirement: Current workspace members expose OAuth registration status

After an explicit live membership refresh, the UI SHALL distinguish membership from local
OAuth registration and SHALL offer OAuth enrollment only for an exact current managed member
whose auth is absent or inactive.

#### Scenario: Current managed member has no OAuth
- **WHEN** live membership confirms an exact managed member and local auth observation reports absent
- **THEN** the workspace card shows OAuth as missing and offers an explicit OAuth registration action
- **AND** no membership replacement is initiated

#### Scenario: Current member is already authenticated
- **WHEN** local auth observation reports the exact current member as active
- **THEN** the UI shows OAuth as registered
- **AND** does not offer a duplicate registration action

#### Scenario: Multiple managed members have exact active OAuth identities
- **WHEN** two or more active OAuth accounts each map exactly to distinct managed member identities
- **THEN** each exact member keeps its own active OAuth status
- **AND** the workspace is not marked identity-ambiguous solely because the active auth count is greater than one

### Requirement: OAuth-only enrollment preserves membership and other auth

The OAuth-only workflow SHALL share the global member-operation control scope but SHALL NOT
remove, invite, replace, quarantine, or delete another member or auth identity.

#### Scenario: Device-code OAuth is issued for an existing current member
- **WHEN** the operator explicitly approves device-code issuance
- **THEN** the system revalidates the current workspace membership and exact catalog identity
- **AND** issues OAuth with no removed member identity
- **AND** preserves all other auth identities

#### Scenario: Identity cannot be proven
- **WHEN** membership, catalog identity, or local OAuth identity is missing, ambiguous, quarantined, or changed
- **THEN** the OAuth enrollment is rejected before device-code issuance
- **AND** no inferred account or membership mutation occurs

### Requirement: OAuth-only enrollment is durable and explicitly advanced

The workflow SHALL persist command intent before OAuth effects and SHALL not automatically replay
an unknown command after response loss or process interruption.

The managed workflow SHALL use the official shared single-active device-code slot as cross-lane
authority. A pre-existing device flow SHALL block managed issuance. Before managed OAuth state is
observed or applied, the slot SHALL still name the exact managed flow; supersession by an ordinary
OAuth start on another lane SHALL fail closed.

#### Scenario: Device-code flow is pending
- **WHEN** a device code has been issued
- **THEN** the UI shows the code and verification URL
- **AND** OAuth status/application advances only after an explicit operator action

#### Scenario: OAuth enrollment completes
- **WHEN** exact target OAuth is verified and persisted
- **THEN** the UI may immediately show the current member as OAuth registered
- **AND** the global control scope is released only after explicit finish

#### Scenario: Another device-code OAuth is already active
- **WHEN** a device-flow slot is already owned before managed device-code issuance
- **THEN** the managed OAuth command is rejected before command intent is claimed
- **AND** the existing device flow is not superseded

#### Scenario: Another lane supersedes the managed device flow
- **WHEN** ordinary OAuth on another lane becomes the current shared device flow after managed issuance
- **THEN** the next managed advance is rejected before OAuth observation or application
- **AND** the managed workflow does not infer success from its stale device code

#### Scenario: OAuth-only device code expires
- **WHEN** an OAuth-only enrollment observes that its device code has expired
- **THEN** the enrollment records a terminal attention state without issuing another device code
- **AND** a new device code requires a new enrollment after explicit finalization and fresh membership validation
