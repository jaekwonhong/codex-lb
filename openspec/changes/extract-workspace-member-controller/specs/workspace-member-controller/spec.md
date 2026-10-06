## ADDED Requirements

### Requirement: Workspace membership control is separated from the inference data plane

The system SHALL provide workspace membership management through a standalone Workspace Member Controller control-plane boundary. Ordinary model requests SHALL route directly through OpenCodex and SHALL NOT traverse the Controller. OpenCodex SHALL remain the authority for ChatGPT/Codex account-pool selection, quota/cooldown state, request failover, and thread/account affinity. The Controller SHALL consume only the account-state projection needed for workspace membership decisions and SHALL NOT maintain an independent inference-routing authority.

#### Scenario: Ordinary inference bypasses the Controller

- **GIVEN** PC1, PC2, or Mac sends an ordinary model request
- **WHEN** OpenCodex routes the request to ChatGPT/Codex or another configured provider
- **THEN** the request is served without traversing the Workspace Member Controller
- **AND** Controller availability does not become an inference-path dependency

#### Scenario: Workspace membership operation uses account state without owning routing

- **GIVEN** a workspace membership decision requires the identity or current state of a ChatGPT/Codex account
- **WHEN** the Workspace Member Controller evaluates that decision
- **THEN** it consumes the defined OpenCodex account-state projection for the exact account identity
- **AND** it does not independently select an inference account, calculate request failover, or establish thread affinity

#### Scenario: Controller outage does not create a second data-plane fallback

- **GIVEN** the Workspace Member Controller is unavailable
- **WHEN** OpenCodex receives an otherwise valid model request
- **THEN** OpenCodex continues to apply its own configured account-pool and provider-routing behavior
- **AND** the system does not fall back to Codex-LB as a second inference router merely because the Controller is unavailable
### Requirement: OpenCodex is the single writer for inference-account runtime state

OpenCodex SHALL be the sole mutable authority for ChatGPT/Codex inference-account credentials, pool eligibility and selection, live quota/cooldown/health state, exact account selection, request retry/failover, and thread/account affinity. The Workspace Member Controller SHALL NOT persist or mutate a parallel authoritative copy of those states. The Controller MAY consume an account-state projection and MAY request an OpenCodex-owned account-management command, but OpenCodex SHALL remain the writer and the Controller SHALL bind only the receipt/evidence needed for its membership workflow.

#### Scenario: Controller evaluates member replacement from account evidence

- **GIVEN** membership policy requires current account quota or eligibility evidence
- **WHEN** the Controller evaluates a workspace-member replacement
- **THEN** it reads the defined OpenCodex account-state projection
- **AND** it does not refresh or write a parallel live account quota/status record as routing authority

#### Scenario: Membership transition needs an account lifecycle change

- **GIVEN** a completed or reconciled membership transition requires the referenced account to change inference eligibility
- **WHEN** the Controller requests that lifecycle change
- **THEN** the change is executed through an OpenCodex-owned account-management boundary
- **AND** the Controller retains only the command identity/receipt required for membership recovery

#### Scenario: Account-state evidence is unavailable

- **GIVEN** a membership decision requires fresh OpenCodex account state
- **WHEN** that evidence is missing, stale, ambiguous, or cannot be bound to the expected account identity
- **THEN** the membership decision fails closed
- **AND** a stale Controller-side snapshot is not promoted to current account truth

### Requirement: Workspace Member Controller is the single writer for membership-control state and effects

The Workspace Member Controller SHALL own workspace catalog and identity, owner/member observation, desired membership intent, membership-specific candidate/policy decisions, membership add/remove/switch/invite/join orchestration, membership-specific rolling mutation limits, canary effect admission, durable effect ownership, unknown-effect state, and no-replay recovery. OpenCodex SHALL NOT perform or journal workspace membership effects merely because an inference account becomes unavailable or quota exhausted.

#### Scenario: Inference account becomes quota exhausted

- **WHEN** OpenCodex marks an account quota exhausted or switches inference to another account
- **THEN** no workspace membership mutation is authorized by that routing event alone
- **AND** any later membership replacement is admitted separately by the Controller's membership policy and journal

#### Scenario: Membership mutation outcome is unknown

- **GIVEN** a member remove/invite operation may have crossed an external effect boundary and its reply is ambiguous
- **WHEN** the workflow is recovered
- **THEN** the Controller retains and reconciles the unknown effect under its durable no-replay rules
- **AND** OpenCodex account failover state is not treated as proof that the membership effect did or did not happen

### Requirement: Account-pool rotation and workspace-member rotation have separate authorities

Inference account-pool rotation SHALL be owned by OpenCodex. Workspace-member rotation SHALL be owned by the Workspace Member Controller. The Controller MAY retain an immutable snapshot of OpenCodex evidence used by a membership decision, but that snapshot SHALL be audit/recovery evidence only and SHALL NOT become a live quota, cooldown, health, or account-selection authority. Account-level quota reset-credit or grant operations required by membership policy SHALL execute through an OpenCodex-owned command boundary rather than a Controller-owned duplicate executor.

#### Scenario: Decision evidence is retained after a member replacement

- **GIVEN** the Controller admitted a replacement using fresh OpenCodex account evidence
- **WHEN** it stores the evidence with the membership operation for audit and recovery
- **THEN** the stored evidence remains immutable for that operation
- **AND** future account-pool routing continues to use OpenCodex's current state rather than the retained snapshot

#### Scenario: Reset-credit operation is required before replacement

- **GIVEN** membership policy requires an account-level reset-credit or grant check before replacing a member
- **WHEN** such an operation is attempted
- **THEN** OpenCodex owns the account-level operation and resulting account state
- **AND** the Controller binds its returned receipt/evidence to the membership evaluation without running a second reset executor

### Requirement: Inference-account credentials are not duplicated into the Controller

The final Workspace Member Controller SHALL NOT persist ChatGPT/Codex inference access tokens, refresh tokens, inference API keys, or a mutable mirror of OpenCodex account credential status. Existing Codex-LB credential-handoff behavior that mutates inference account rows, routing caches, API-key caches, or credential refresh state SHALL be replaced by an OpenCodex account-management adapter or retired. Workspace-admin browser/session capabilities used solely by the qualified membership-effect adapter MAY remain in the membership-control boundary because they are not inference routing credentials.

#### Scenario: Existing member auth handoff is extracted

- **GIVEN** the legacy handoff workflow currently changes Codex-LB account status or routing-visible caches
- **WHEN** that workflow is moved behind the Controller boundary
- **THEN** those account-runtime writes are replaced by OpenCodex-owned operations or removed
- **AND** no ChatGPT/Codex inference token is copied into Controller persistence
