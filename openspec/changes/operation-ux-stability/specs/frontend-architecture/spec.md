## ADDED Requirements

### Requirement: Destructive confirmations preserve the confirmed target until success

Management confirmation dialogs SHALL remain bound to the exact target or filter
snapshot displayed to the operator until that request succeeds or the operator
explicitly cancels. A failed or partially failed request SHALL remain visible and
SHALL NOT be represented as a completed action merely by closing the dialog.

#### Scenario: A destructive request fails

- **WHEN** a confirmed delete, purge, or run-now request fails
- **THEN** the confirmation remains open with the same target
- **AND** the failure is visible within that confirmation
- **AND** the client does not automatically retry the request

#### Scenario: A filtered deletion is confirmed

- **WHEN** an operator confirms deletion of the currently filtered sticky sessions
- **THEN** the request uses the same filter snapshot used to present the confirmation
- **AND** later filter input changes do not broaden or replace the confirmed target

### Requirement: Handled UI mutations do not leak rejected promises

UI event handlers that intentionally delegate failure presentation to maintained
mutation state SHALL consume the corresponding rejected promise. This handling
MUST NOT convert failure to success, retry the request, or hide the maintained error.

#### Scenario: A handled mutation rejects

- **WHEN** an immediate UI mutation rejects and the maintained mutation state owns error presentation
- **THEN** the event handler consumes the rejected promise
- **AND** the maintained error remains visible
- **AND** the request is not retried or represented as successful
