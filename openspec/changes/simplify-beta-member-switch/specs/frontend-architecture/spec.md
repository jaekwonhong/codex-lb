## ADDED Requirements

### Requirement: Explicit minimal member switching

The Accounts page SHALL expose catalog loading, preview, single replacement
submission, status refresh, authentication preparation, authentication browser
launch, authentication confirmation and finalization as explicit operator actions.
Page load, navigation, focus, reconnect and restored browser storage SHALL NOT
submit a member-switch command, contact Companion or advance authentication.
Accounts MAY restore a run using a read-only stored-status GET to the backend.
Read-only users SHALL NOT be able to invoke control actions or read private run details.

#### Scenario: Operator opens an unrelated page or restores an old run

- **WHEN** the dashboard mounts, navigates or restores stored member-switch state
- **THEN** no member-switch command, OAuth browser or rotation request is issued
- **AND** a restored run remains visible on Accounts without being resumed

#### Scenario: Operator confirms a preview

- **WHEN** the operator explicitly confirms an unexpired, identity-matching preview
- **THEN** the frontend submits at most one replacement request for that action
- **AND** it does not reconcile, finalize a blocking run or retry on its own

#### Scenario: Mutation result cannot be confirmed

- **WHEN** a response is lost, malformed or has a mismatched identity
- **THEN** the backend retains the flow and known operation identifiers
- **AND** it blocks another replacement and describes the uncertain outcome

#### Scenario: Stored run cannot be read

- **WHEN** server state cannot be read or browser storage contains an unresolved legacy run
- **THEN** no new replacement is admitted and no recovery evidence is deleted
- **AND** an optional browser locator never grants execution permission

#### Scenario: Membership succeeds but authentication has not completed

- **WHEN** Companion reports membership complete
- **THEN** the UI labels only the membership stage complete
- **AND** authentication and finalization require separate explicit actions

### Requirement: Route loading and failures remain visible

Lazy routes SHALL show a loading status. Route rendering failures SHALL preserve
navigation and show a reload action. Unknown routes SHALL show a not-found state.

#### Scenario: Route chunk fails or path is unknown

- **WHEN** a route fails to load or has no matching route
- **THEN** the dashboard shows an actionable message rather than blank content

### Requirement: Account alias failure retains the operator's draft

An unsuccessful account-alias save SHALL keep the editor and entered value
visible, display the failure, and handle the rejected mutation promise.

#### Scenario: Alias save request fails

- **WHEN** an operator submits an alias and the server rejects the save
- **THEN** the entered alias remains editable and the failure is visible
- **AND** no unhandled promise rejection escapes the event handler

### Requirement: Initial page failures are not indefinite loading states

Accounts, Settings and Dashboard SHALL distinguish an initial request failure from loading,
display the error, and retain an explicit retry or refresh action. Previously
loaded data SHALL remain visible when a later refresh fails.

#### Scenario: Accounts cannot be loaded

- **WHEN** the initial account-list request fails
- **THEN** the error and retry control are visible instead of an indefinite skeleton
- **AND** retry is issued only after operator interaction

### Requirement: Dashboard fits small viewports

Dashboard layout SHALL contain its controls and content at mobile, tablet and
desktop widths without horizontal page overflow.

#### Scenario: Dashboard opens at a 390-pixel viewport

- **WHEN** the dashboard renders at a 390-pixel viewport
- **THEN** document content does not extend beyond the viewport width
- **AND** controls remain reachable rather than being clipped
