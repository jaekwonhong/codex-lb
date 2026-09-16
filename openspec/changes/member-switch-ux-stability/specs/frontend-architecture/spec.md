## ADDED Requirements

### Requirement: Member-switch replies belong to one UI lifecycle
Only the current request in the current mounted `accounts:write` lifecycle SHALL publish
member-switch UI state or its run locator. Explicit refresh MAY supersede initial
stored-state restoration. Unmount or loss of `accounts:write` SHALL cancel local requests
and invalidate their replies, without claiming that the server cancelled an effect.

#### Scenario: Initial restoration finishes after explicit refresh
- **WHEN** the older initial GET resolves after a newer explicit stored-state read
- **THEN** it does not replace the displayed run or locator
- **AND** no POST is automatically repeated

#### Scenario: Access changes while a command response is in flight
- **WHEN** a previous lifecycle's response arrives after access is revoked or restored
- **THEN** it cannot replace the new lifecycle's state, error or request ownership
- **AND** new commands require a successful current stored-state read

### Requirement: Stored recovery is consistent and conservative
Mount and explicit refresh SHALL use the same stored-state resolution. A response
with HTTP 404 and the `run_not_found` code MAY clear only the exact missing browser
locator. Other failures SHALL preserve it. Failed refresh SHALL disable command
execution until a successful explicit stored read; already displayed state MAY remain
visible but SHALL NOT be presented as newly checked.

#### Scenario: A rejected create left a locator but no server run
- **WHEN** the active-run GET is empty and that locator returns confirmed run_not_found
- **THEN** restoration completes as idle without an error or repeated create

#### Scenario: Stored refresh fails
- **WHEN** the server cannot supply a fresh stored run
- **THEN** the previous run remains visible but command controls are unavailable
- **AND** the operator can request another stored-state refresh

### Requirement: Manual feedback identifies the safe next action
The panel SHALL distinguish stored-state refresh, explicit external execution and
completed-record dismissal. Known expiry, stale revision and unresolved-outcome
messages SHALL explain the applicable manual next action while retaining diagnostic
codes. Feedback SHALL NOT authorize replay, force release or implicit authentication.

#### Scenario: Preview has expired
- **WHEN** the server rejects start with preview_expired
- **THEN** the panel explains stored refresh followed by preview cancellation and a
  new preview, rather than suggesting the same start request can succeed after refresh
