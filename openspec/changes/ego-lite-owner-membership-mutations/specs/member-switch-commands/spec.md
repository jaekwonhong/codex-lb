## ADDED Requirements

### Requirement: Owner membership mutations use the exact owner Ego Lite profile
The managed member-switch implementation SHALL execute member deletion, invitation creation, and invitation cancellation through the same deterministic owner Ego Lite Profile and Task Space used for owner membership observation. The owner-specific personal-account confirmation performed before mutation and owner cleanup performed after success or failure SHALL use that same Ego Lite authority. It SHALL resolve the workspace owner email to exactly one active managed account, derive `CodexLB-<stable account id>`, verify the current ChatGPT session email equals the workspace owner, and use the exact workspace account id. It MUST NOT launch, attach to, or fall back to a legacy owner CDP browser for owner personal checks, cleanup, or membership mutations.

#### Scenario: Explicit member replacement performs owner mutations
- **WHEN** a managed member-switch operation must delete a current member, cancel a pending invitation, or invite the selected target
- **THEN** the operation executes inside the exact owner Ego Lite Task Space
- **AND** subsequent owner membership verification uses that same Ego Lite authority
- **AND** no owner CDP mutation fallback occurs

#### Scenario: Owner login identity cannot be proven
- **WHEN** the deterministic owner profile is missing, logged out, logged in as another email, ambiguous, or its Task Space authority cannot be proven
- **THEN** the mutation fails closed before sending a membership mutation request
- **AND** it does not try another profile, CDP port, or system browser

### Requirement: Unknown owner mutation effects are reconciled without replay
A process timeout, transport failure, or Task Space outcome that cannot prove whether a mutation request executed SHALL be represented as an ambiguous mutation outcome. The system SHALL use subsequent exact owner Ego membership observations to determine the resulting state and SHALL NOT repeat the mutation merely because the immediate response is unknown.

#### Scenario: Delete response is unknown
- **WHEN** an exact member DELETE may have been delivered but its result is unknown
- **THEN** removal verification reads owner membership state without replaying DELETE
- **AND** only the existing exact identity-missing 404 contract may authorize its bounded retry

#### Scenario: Invitation response is unknown
- **WHEN** an invitation POST may have been delivered but its result is unknown
- **THEN** the operation observes member and invitation state before deciding whether the invitation exists
- **AND** it does not immediately issue a second invitation

#### Scenario: Invite cancellation response is unknown
- **WHEN** cancellation may have been delivered but its result is unknown
- **THEN** the cleanup path observes the exact invitation until absence is confirmed or the bounded observation fails
- **AND** it does not repeat the cancellation command

### Requirement: Owner Ego mutation capability is negotiated before mutation-capable work
The Companion SHALL advertise `ego_lite_owner_membership_mutation_v1`. The backend SHALL require this capability before creating a new managed member-switch run and again immediately before executing a `start` that may perform membership mutations. Reconciliation of an already-claimed start SHALL remain receipt/observation-only and SHALL NOT replay the mutation merely because this capability later disappears. OAuth-only registration and catalog refresh SHALL continue to require only the owner observation capability.

#### Scenario: Backend and Companion mutation capabilities differ
- **WHEN** a new or retained member-switch run would enter the mutation phase but the Companion lacks `ego_lite_owner_membership_mutation_v1`
- **THEN** the backend rejects the transition before claiming or replaying mutation intent
- **AND** legacy owner CDP mutation cannot be reached as a compatibility fallback
