## ADDED Requirements

### Requirement: Workspace cards distinguish actual membership from switch candidates

The manual member-switch workspace card SHALL show the workspace owner and the latest explicitly observed non-owner workspace member identities separately from the configured switch candidates.

#### Scenario: Explicit list refresh observes membership
- **WHEN** an authorized operator refreshes the member-switch list while no managed switch is active
- **THEN** the application explicitly inspects each configured workspace membership
- **AND** the card shows the observed member email(s) under the owner
- **AND** a failed workspace inspection is represented as an observation failure rather than as an empty confirmed membership

#### Scenario: Observed user id corrects an exact known managed account
- **GIVEN** a workspace observation contains an unambiguous member email that exactly matches an included managed account
- **WHEN** the observed upstream user id differs from the stored user id
- **THEN** the Companion updates only that account's stored user id and regenerates the candidate catalog
- **AND** it does not add unknown accounts, change group assignments, or mark a login-required account ready

#### Scenario: Active work blocks catalog refresh
- **GIVEN** a managed member-switch run is active
- **WHEN** a catalog membership refresh is requested
- **THEN** no workspace membership inspection or identity reconciliation is performed

#### Scenario: Finalized switch refreshes display
- **WHEN** the operator successfully finalizes a managed member switch
- **THEN** the client performs one explicit catalog membership refresh after finalization
- **AND** it does not replay the completed member-switch operation
