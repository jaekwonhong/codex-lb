## ADDED Requirements

### Requirement: Failed owner preflight preserves user assistance
When owner personal preparation fails before it is confirmed, the managed member-switch runner SHALL NOT call owner personal preparation again through failure cleanup. A user-handed-off Space SHALL remain available for user login; uncertain preparation SHALL not be repeated merely to clean up.

#### Scenario: Owner needs login
- **WHEN** owner personal preparation returns ego_owner_profile_login_required
- **THEN** the operation fails before membership changes
- **AND** cleanup does not take over, navigate, close or repeat owner preparation

### Requirement: Known owner preflight failure can be explicitly closed
The backend SHALL offer finish for a terminal owner login-required, identity-mismatch or identity-unavailable preflight failure only when a contiguous trace from queued through owner confirmation to matching failed result proves no mutation, no invitation settlement and no target handoff/browser operation. A missing, truncated, out-of-order or contradictory trace SHALL NOT authorize finish. Existing narrow legacy pre-membership closeout remains compatible.

#### Scenario: Exact pre-effect failure
- **WHEN** the complete durable operation trace confirms owner preflight failure before membership work
- **THEN** the user can explicitly finish through the existing finalization path and refresh the catalog
- **AND** finish does not resend membership or browser effects

#### Scenario: Uncertain or post-effect failure
- **WHEN** the result is uncertain, mutation metadata exists, or trace completeness cannot be verified
- **THEN** retained ownership is preserved and no finish permission is added

### Requirement: Recovery guidance follows available controls
An active-run owner assistance hint SHALL identify the current recovery path instead of instructing a user to activate a disabled catalog refresh. The finish label in guidance SHALL match the visible action, and no finish instruction SHALL be rendered as available without server permission.

#### Scenario: Finish is blocked
- **WHEN** an owner failure has no allowed finish action
- **THEN** the hint directs saved-state inspection and operator review without claiming a reset or retry path is available

#### Scenario: Finishing preflight assistance does not reclaim the browser
- **WHEN** a known pre-membership failure is explicitly finalized
- **THEN** the client discards its stale catalog and does not automatically issue browser-backed catalog refresh
- **AND** the user can explicitly load the catalog after completing login assistance
- **AND** normal successful membership/OAuth completion retains its existing catalog refresh

#### Scenario: Lost closeout reply recovered from saved state
- **WHEN** a terminal member-switch or OAuth-only result is recovered by stored-state refresh or explicit reconciliation
- **THEN** any prior catalog observation is discarded without an automatic browser-backed refresh
- **AND** an unfinished closeout exposes guidance for the server-permitted reconciliation action, not an unavailable membership-observation action
- **AND** pending observation is not described as a termination request merely because the previous result was an owner failure
