## ADDED Requirements

### Requirement: Destructive confirmation retains its target and result
Account deletion, account usage reset and API-key deletion confirmations SHALL
display the selected immutable local ID and identifying label. A pending request
SHALL keep its dialog and options visible and prevent duplicate submission or
misleading cancellation. Only confirmed success SHALL dismiss the dialog.
A failed request SHALL preserve its target and options, display the error in the
dialog, and SHALL NOT trigger automatic replay or an unhandled promise rejection.
Account identity displays SHALL respect the existing privacy setting.

#### Scenario: Deleting an account with history fails
- **WHEN** the operator confirms one account with history deletion checked and the request fails
- **THEN** the same ID and checked option remain visible with the error
- **AND** no further deletion is sent without explicit confirmation

#### Scenario: A usage reset is retried explicitly after response loss
- **WHEN** the same retained usage-reset dialog is confirmed again after failure
- **THEN** the existing account-scoped redemption ID is reused
- **AND** cancel before initial confirmation sends no request

### Requirement: Confirmation rechecks current eligibility
The reviewed confirmation consumers SHALL disable execution if current write
permission is unavailable, another mutation is pending, the source list has an
error, or the captured target ID no longer exists in that list. They SHALL NOT
silently substitute the newly selected account or key. The API management page
SHALL retain browsing for read-only users while disabling its write controls.

#### Scenario: A target disappears or write permission changes while a dialog is open
- **WHEN** the current list lacks the captured target or write permission is lost
- **THEN** confirming cannot dispatch a mutation and the operator may dismiss the dialog

#### Scenario: Read-only API management
- **WHEN** a read-only user opens the API management page
- **THEN** key inspection and selection remain available but creation and modification controls are disabled
