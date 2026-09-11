## ADDED Requirements

### Requirement: Manual membership failure cannot authorize another invitation
A managed membership execution SHALL issue at most one invitation and use at most
one exact-pending-invitation URL fallback. Failed or unobserved settlement SHALL NOT
cancel or reissue an invitation, repeat URL approval, or release operation ownership.
Bounded stored/owner observations remain permitted within the explicit command.

#### Scenario: The one fallback leaves the invitation pending
- **WHEN** bounded post-fallback observation does not confirm the intended member
- **THEN** execution records failure and retains its operation and invitation evidence
- **AND** no second approval, invitation cancellation or reissue is performed

### Requirement: An uncertain delete is observed rather than replayed
A deletion timeout, transport failure or server error SHALL NOT authorize a second
delete. The original attempt MAY be resolved by the existing bounded absence checks.
The existing exact-identity-missing rejection contract is not an uncertain outcome.

#### Scenario: A delete reply is lost and the member is still visible
- **WHEN** bounded observations cannot prove absence after the first delete
- **THEN** the operation fails with its ownership retained and no second delete

### Requirement: Known pending invitations fence removal
When the initial execution inspection already contains a pending invitation and the
target is not the sole active member, the managed operation SHALL stop before
deleting a member or issuing an invitation. It SHALL preserve that existing evidence.

#### Scenario: Another invitation is present before removal
- **WHEN** a removable member and a pending invitation are observed at execution
- **THEN** no removal, invitation cancellation, invitation issue or approval occurs

### Requirement: Recipient navigation does not restart acceptance
The concrete recipient browser SHALL execute one acceptance navigation. An uncertain
post-acceptance workspace observation SHALL be returned without navigating through
login and accepting the invitation again. Retrying attachment or observation on the
same newly created target before acting is not another acceptance action.

#### Scenario: Acceptance transport succeeds but the workspace is not yet visible
- **WHEN** the concrete driver reports workspace absent or unavailable
- **THEN** it does not perform another acceptance navigation or acceptance POST

### Requirement: Rejected page observations cannot authorize native clicks
The page-side origin, document-epoch and current-control validation SHALL govern
the acceptance pointer action. A false, null or lost result SHALL NOT fall through
to a native click at stale coordinates.

#### Scenario: The document changed after observing the control
- **WHEN** the page-side action rejects the old observation
- **THEN** the operation returns failure without a native pointer fallback

### Requirement: Acceptance preserves the established account-scoping contract
Acceptance SHALL use the target workspace in the request path without attaching the
recipient's personal-account scope header to that POST. Subsequent account visibility
GET requests SHALL retain the existing source-account scope. This restores the
repository contract established by Companion commit 3fdb33d, not a new upstream API.

#### Scenario: Recipient personal session accepts a target workspace invitation
- **WHEN** the acceptance request is constructed
- **THEN** the acceptance POST has the target workspace path and no personal scope header
- **AND** the visibility GET retains its existing source-account header
