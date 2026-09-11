## ADDED Requirements

### Requirement: Recipient membership lifecycle uses exact Ego Lite authority
The managed member-switch implementation SHALL route recipient personal-session confirmation, outgoing workspace absence confirmation, incoming workspace presence/hold confirmation, invitation acceptance, and recipient operational cleanup through the managed account whose stable ID corresponds to the exact recipient email and user ID. The runtime SHALL derive `CodexLB-<stable account id>` and `codex-lb-recipient-<stable account id>`, verify the current ChatGPT session email and user ID before any membership-related effect, and MUST NOT launch, attach to, or fall back to a recipient CDP browser for these managed-flow actions.

#### Scenario: Incoming member settlement
- **WHEN** a managed member-switch run must confirm or accept the target workspace invitation
- **THEN** the exact recipient Ego Lite Space is used for acceptance and workspace confirmation
- **AND** no recipient CDP session is opened as a fallback

#### Scenario: Outgoing member removal verification
- **WHEN** a removed member must be confirmed in Personal and the prior workspace must be absent
- **THEN** the exact outgoing recipient Ego Lite Space is used
- **AND** exact email/user identity is verified before the observation is trusted

### Requirement: Recipient acceptance is bound and non-replayable when uncertain
Invitation acceptance SHALL bind the exact target email and workspace account ID before sending an acceptance request. If the process, transport, or result becomes uncertain after the request may have been delivered, the system SHALL rely on subsequent owner membership and recipient workspace observations to settle the result and SHALL NOT automatically send a second acceptance request.

#### Scenario: Acceptance effect is uncertain
- **WHEN** the acceptance request may have been delivered but the immediate result is unknown
- **THEN** the run continues to bounded membership/workspace observation
- **AND** the acceptance request is not replayed

#### Scenario: Recipient identity cannot be proven
- **WHEN** the deterministic recipient profile is missing, logged out, logged in as another account, or has a different user ID
- **THEN** acceptance and workspace effects are blocked before the request
- **AND** no CDP/system-browser fallback is attempted

### Requirement: Recipient Ego lifecycle capability is negotiated before managed mutation work
The Companion SHALL advertise `ego_lite_recipient_membership_lifecycle_v1`. The backend SHALL require it when creating a new managed member-switch run and again immediately before a retained run enters `start`. Catalog refresh and OAuth-only registration SHALL not require this capability. Reconciliation of already-claimed work SHALL remain observation/receipt based and SHALL not replay effects merely because the capability later disappears.

#### Scenario: Mixed backend and Companion versions
- **WHEN** the Companion lacks `ego_lite_recipient_membership_lifecycle_v1`
- **THEN** a new managed member-switch run or unclaimed `start` is rejected before mutation intent
- **AND** legacy recipient CDP behavior is not used as compatibility fallback
