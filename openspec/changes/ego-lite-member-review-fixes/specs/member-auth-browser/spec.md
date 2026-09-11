## ADDED Requirements

### Requirement: Unknown member-session effects remain unknown
The system SHALL preserve unknown runtime outcomes through the service response and durable participant receipt and SHALL NOT replay them as known failures.
#### Scenario: Session check times out
- **WHEN** runtime session checking returns an unknown outcome
- **THEN** the command remains pending and duplicate or new effect commands cannot repeat it

### Requirement: Exact close recovery uses observation only
The system SHALL bind a close to the persisted exact Ego profile and Task Space identity, perform bounded post-close observation, and expose explicit observation-only reconciliation. Ordinary GET receipts SHALL remain stored reads.
#### Scenario: Space disappears after delayed close
- **WHEN** a recorded close remains pending but its exact recorded target is now absent
- **THEN** explicit reconciliation durably confirms closure without another close or any browser mutation
#### Scenario: Target authority is insufficient
- **WHEN** the receipt lacks exact target identity or the current target conflicts with that identity
- **THEN** reconciliation retains the pending command and does not act on any replacement space

### Requirement: Same-handoff login recovery is executable
The system SHALL permit explicit exact-member session preparation after a confirmed close or known browser-open failure while the same OAuth handoff is active and no browser target or pending command remains.
#### Scenario: Close and reopen an unfinished auth page
- **WHEN** the auth target is closed before authorization completes
- **THEN** the user can recheck the exact login and reopen the same OAuth handoff without new membership or OAuth preparation effects
- **AND** the run remains in needs-attention recovery state and browser reopen is not offered until that exact-member session recheck succeeds

#### Scenario: Known browser-open failure requires recheck
- **WHEN** an explicit browser-open attempt returns a known failure without an accepted browser target
- **THEN** the same OAuth handoff remains active in needs-attention recovery state but another browser-open action is not offered until exact-member session preparation succeeds

### Requirement: Availability failures are not logout evidence
The system SHALL classify failed session queries separately from confirmed unauthenticated sessions and SHALL preserve the current page for HTTP throttling, server errors, invalid responses, and network failure.
#### Scenario: Session endpoint returns HTTP 503
- **WHEN** session verification receives a transient server failure
- **THEN** it reports identity unavailable and does not navigate to login or claim the session has expired
