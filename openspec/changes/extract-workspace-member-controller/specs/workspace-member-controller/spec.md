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

### Requirement: Workspace members bind to exact OpenCodex account identities

The Controller SHALL use the exact OpenCodex `account_id` as the durable foreign account key for a workspace-member binding. `workspace_account_id`, `preset_id`, member `user_id`, normalized member email, OpenCodex selector, alias and log label SHALL remain distinct identity namespaces. Email, selector, alias, display name or log label alone SHALL NOT establish or repair a member-to-account binding. Credential generation SHALL fence account evidence but SHALL NOT be the durable member identity.

#### Scenario: Selector is remapped

- **GIVEN** a workspace member is durably bound to one OpenCodex account id
- **WHEN** an account selector is removed or remapped to another account
- **THEN** the durable binding remains keyed by the original exact account id
- **AND** a selector-targeted command fails closed unless OpenCodex resolves the selector back to that bound account id

#### Scenario: Email matches but exact identity is unproven

- **GIVEN** a workspace member email matches an OpenCodex account label or projected email
- **WHEN** exact account/member identity has not been established by the qualified binding flow
- **THEN** the Controller does not create or repair the account binding from email alone

### Requirement: Account-state decisions are freshness and generation fenced

The OpenCodex adapter SHALL return an exact-account state projection with capture time, normalized selection/quota/health state, an opaque state revision, and the live credential generation for pool credential-scoped evidence or native-main identity generation for main-account evidence. Membership decisions requiring live account state SHALL reject projections older than the configured Controller `account_state_max_age`. Quota-dependent decisions SHALL also reject unknown or insufficiently fresh quota evidence. A generation or relevant state-revision change SHALL require re-read and re-evaluation rather than reuse of stale decision evidence.

#### Scenario: Credential refresh advances generation before mutation

- **GIVEN** a membership replacement was evaluated against account generation N
- **WHEN** OpenCodex advances that account to generation N+1 before the account-sensitive command or membership effect
- **THEN** the Controller does not use generation N evidence to authorize the action
- **AND** it obtains a fresh exact-account projection and re-evaluates the affected preconditions
- **AND** the durable member-to-account binding is not remapped merely because the credential generation changed

#### Scenario: Quota state is unknown

- **GIVEN** replacement policy requires current quota evidence
- **WHEN** OpenCodex reports `quota_state=unknown` or the required quota observation is missing/stale
- **THEN** the Controller blocks that quota-dependent replacement
- **AND** it does not derive an authoritative replacement verdict by independently recalculating OpenCodex routing eligibility from raw quota percentages

### Requirement: OpenCodex account evidence retained by the Controller is immutable operation evidence

When a membership decision consumes OpenCodex account state, the Controller SHALL bind the exact account id, applicable credential/main identity generation, state revision, observation time, normalized selection/quota state and only the quota-window evidence relevant to that decision into the membership-operation journal. The retained record SHALL be immutable historical evidence and SHALL NOT be refreshed in place or used as current account routing truth.

#### Scenario: Later routing state differs from retained membership evidence

- **GIVEN** a completed membership operation retains the account evidence that authorized it
- **WHEN** OpenCodex later changes quota, cooldown, health, credential generation or account selection
- **THEN** the operation journal keeps its original evidence unchanged for audit/recovery
- **AND** all new membership decisions read current state from OpenCodex rather than the historical snapshot

### Requirement: Account-management commands target an exact fenced account

Any Controller-initiated OpenCodex account-management command SHALL identify the exact account and SHALL include the applicable identity/generation fence and an idempotency command id; it MAY also include the expected projected state revision. OpenCodex SHALL execute against that exact account or fail closed and SHALL NOT redirect the command to another pool account. An unknown command outcome SHALL be reconciled by an exact state read before any retry.

#### Scenario: Account command outcome is unknown

- **GIVEN** the Controller sent an exact-account management command with a command id and generation fence
- **WHEN** delivery may have crossed the effect boundary but the reply is unavailable
- **THEN** the Controller does not issue a blind replacement command
- **AND** it reads the exact OpenCodex account state and reconciles the command outcome before any retry

### Requirement: Workspace catalog and membership observation use a data-plane-independent read boundary

Workspace catalog, workspace/member/owner read models, and membership observation models SHALL be owned by the Workspace Member Controller domain boundary and SHALL NOT depend on Codex-LB request-routing, account-repository, dashboard-model, database-model, or dependency-container types. The read boundary SHALL expose separate catalog and membership-observation ports so read-only Controller workflows can be constructed without importing membership mutation effects. During migration, legacy Codex-LB surfaces MAY re-export the extracted models only when the serialized wire contract remains unchanged.

#### Scenario: Legacy member-switch route serializes an extracted catalog model

- **GIVEN** an existing Codex-LB route still imports `Catalog` through the legacy member-switch schema module
- **WHEN** it serializes a workspace catalog returned by the extracted Controller domain model
- **THEN** the existing camelCase field aliases and UTC datetime wire representation remain unchanged
- **AND** the underlying model is owned by the standalone Controller domain rather than the dashboard schema layer

#### Scenario: Read-only observation workflow is constructed without mutation ports

- **GIVEN** a Controller workflow only needs the workspace catalog and current membership observation
- **WHEN** its dependencies are wired
- **THEN** it can depend only on the independent catalog and membership-observation ports
- **AND** it does not require member mutation, proxy routing, account repository, or dashboard dependencies

### Requirement: Controller persistence is accessed through data-plane-independent contracts

The Workspace Member Controller core SHALL access workspace intent and membership-operation journal state through Controller-owned persistence contracts rather than importing Codex-LB ORM/account/proxy types. During migration, compatibility adapters MAY reuse existing durable workspace-intent and member-switch journal tables, but the Controller core SHALL NOT create or maintain a duplicate mutable authority for the same intent or operation. The read contract SHALL expose only the fields required for Controller status/recovery and SHALL NOT expose raw stored workflow payloads, command fingerprints/hashes, inference-account credentials, or Codex-LB routing cache state.

#### Scenario: Read service reports an active legacy journal operation

- **GIVEN** an active membership operation is stored in the existing Codex-LB member-switch journal
- **WHEN** the Controller read service loads status through the compatibility persistence adapter
- **THEN** it can report operation id, kind, revision, pending action, and command id
- **AND** raw journal payload and command hash are not exposed through the Controller persistence/read model
- **AND** no Codex-LB `Account` lookup is required for that read

#### Scenario: Workspace intent has not yet been written

- **GIVEN** a managed workspace has no durable automatic-rotation intent row
- **WHEN** the read service asks the workspace-intent contract for current state
- **THEN** the compatibility adapter returns the existing disabled/version-zero default semantics
- **AND** it does not create a row on the read path

### Requirement: Initial Controller HTTP surface is read-only

Before mutation extraction and standalone service authentication are qualified, the Controller SHALL expose only read operations for catalog, Controller status, and exact-workspace membership observation. The read router SHALL contain no POST, PUT, PATCH, or DELETE operation. Observation responses SHALL be accepted only when workspace id, workspace account id, and catalog fingerprint match the current catalog identity; mismatches SHALL fail closed rather than being returned as authoritative membership state. Authentication and process-level exposure SHALL be added by the standalone packaging slice before production network exposure.

#### Scenario: Observation returns a different workspace account

- **GIVEN** the catalog binds `workspace-1` to one `workspace_account_id`
- **WHEN** the observation adapter returns the same workspace id with a different workspace account id
- **THEN** the Controller read API rejects the observation as an identity mismatch
- **AND** the mismatched observation is not returned as current membership state

#### Scenario: Read-only router is inspected before standalone packaging

- **WHEN** the initial Controller router is constructed
- **THEN** its application methods are limited to GET/HEAD semantics
- **AND** no membership intent update, member mutation, or account-management command route exists

### Requirement: Controller reads exact non-secret account state from OpenCodex without causing quota probes

OpenCodex SHALL expose a management-authenticated exact-account read projection for the Workspace Member Controller. The read SHALL require the raw management admin principal, SHALL accept exactly one requested account id, SHALL NOT silently substitute another pool account, and SHALL NOT trigger an upstream quota/credential probe merely to satisfy the Controller read. It SHALL project only OpenCodex-owned cached/runtime state; unobserved quota SHALL remain `unknown`. The projection SHALL contain the applicable pool credential generation or native-main identity generation, normalized health/selection/quota state, observation timestamps, an opaque deterministic state revision, and only non-secret decision evidence. It SHALL NOT contain access tokens, refresh tokens, cookies, inference API keys, raw upstream authorization material, or raw upstream quota responses.

#### Scenario: Controller reads a cold exact account

- **GIVEN** an exact OpenCodex pool account exists with a live credential but no currently observed quota snapshot
- **WHEN** the Controller state endpoint is read for that account id
- **THEN** the response identifies that exact account and current credential generation
- **AND** quota state is returned as `unknown` rather than probing upstream
- **AND** no other account is refreshed or selected as a substitute

#### Scenario: Repeated read sees unchanged account state

- **GIVEN** credential generation, selection state, health, quota, cooldown and reset-credit evidence have not changed
- **WHEN** the same exact account is read twice at different observation times
- **THEN** the `observedAt` values may differ
- **AND** the deterministic `stateRevision` remains identical

#### Scenario: Non-admin management principal requests Controller state

- **WHEN** a GUI session, missing principal, or data-plane caller attempts to use the Controller account-state management route
- **THEN** OpenCodex refuses the route
- **AND** no account-state projection is returned

### Requirement: Controller OpenCodex adapter validates exact identity and freshness without becoming routing authority

The Controller's OpenCodex account-state adapter SHALL send the exact durable `opencodex_account_id` to the OpenCodex projection and SHALL reject a successful response whose returned account id differs. It SHALL validate the generation namespace and state-revision shape before returning a projection to Controller logic. It SHALL expose freshness checks over OpenCodex observation timestamps but SHALL NOT independently infer account selection eligibility from raw quota percentages. Missing accounts, authorization failures, malformed projections and transport failures SHALL be explicit fail-closed errors and SHALL NOT cause fallback to another account.

#### Scenario: OpenCodex response names another account

- **GIVEN** the Controller requested account A
- **WHEN** the management response is otherwise valid but names account B
- **THEN** the adapter rejects the projection as an identity mismatch
- **AND** it does not retry the read against account B

#### Scenario: Projection is stale for membership policy

- **GIVEN** the adapter returned a schema-valid exact-account projection
- **WHEN** its `observedAt` or required `quotaObservedAt` exceeds the Controller policy freshness bound
- **THEN** the projection helper reports it stale
- **AND** downstream membership policy must obtain a new OpenCodex projection before using that evidence

### Requirement: Membership add/remove/switch commands are exact and freshly admitted before effect ownership

The Workspace Member Controller SHALL model `add`, `remove`, and `switch` as explicit membership mutation commands. A new command SHALL bind an immutable operation id, command id, expected journal revision, exact workspace id, exact workspace account id, catalog fingerprint, and action-appropriate incoming/outgoing member identities. Before the command can own an external effect, the Controller SHALL re-read the workspace catalog and membership observation, SHALL require the exact catalog/workspace identities to match, SHALL require the observation to be complete, available, owner-verified, non-ambiguous and fresh, and SHALL reject an outgoing identity that is not currently observed. The default extracted admission freshness bound is 30 seconds. The workspace owner SHALL NOT be accepted as an incoming add/switch target.

#### Scenario: Switch target changed since the command was built

- **GIVEN** a switch command names one catalog fingerprint and exact incoming/outgoing identities
- **WHEN** the current catalog fingerprint differs or the outgoing identity is no longer present in the authoritative membership observation
- **THEN** the Controller refuses admission before claiming the external effect
- **AND** no membership mutation is sent

#### Scenario: Membership observation is stale

- **GIVEN** the exact workspace catalog still matches
- **WHEN** the authoritative membership observation is older than the configured mutation-admission freshness bound
- **THEN** the Controller refuses the command as stale
- **AND** it does not treat the old member list as current effect authorization

### Requirement: Membership effects use a durable claim-before-effect no-replay journal

Before an add/remove/switch external effect may execute, the Controller SHALL durably claim the operation using the command id, action, expected revision and a canonical request fingerprint. The claim and command receipt SHALL commit before the effect port is invoked. The Controller SHALL durably mark the claimed operation as effect-pending before the external effect call. A command id already recorded with the same fingerprint SHALL be idempotent and SHALL NOT execute the effect again. Reuse of the same command identity with different request identity SHALL fail closed.

#### Scenario: Process stops after durable claim but before a usable effect response

- **GIVEN** the command receipt and pending effect ownership were committed
- **WHEN** the external mutation may have been sent but its reply is lost or the Controller restarts
- **THEN** the operation remains durably pending with no TTL-based replay
- **AND** submitting the same command again does not call the external execute method a second time

#### Scenario: Duplicate command is received after successful settlement

- **GIVEN** a command id/fingerprint already produced a terminal membership receipt
- **WHEN** the exact command is submitted again
- **THEN** the Controller returns the retained terminal operation state
- **AND** no add/remove/switch effect is repeated

### Requirement: Unknown membership effects reconcile from the original command receipt identity only

Recovery of a pending membership effect SHALL call an observational reconciliation boundary using the original operation id, command id and request fingerprint. Recovery SHALL NOT call the execute boundary as a substitute for a missing receipt. A reconciled receipt SHALL match the original operation id, command id, fingerprint, action, workspace id and workspace account id before it can settle the journal. If no authoritative receipt/evidence is available, the operation SHALL remain pending/outcome-unknown.

A completed receipt SHALL carry action-appropriate confirmed effect evidence and final membership confirmation. An authoritative non-effect receipt MAY close the operation as failed/retryable history only when it proves no confirmed or unknown membership effect remains. A partial or ambiguous effect SHALL NOT be converted into authoritative non-effect merely to release the journal.

#### Scenario: Reconciliation returns no receipt

- **GIVEN** an add/remove/switch command is durably pending after an ambiguous delivery
- **WHEN** the effect adapter cannot find authoritative evidence for the original command identity
- **THEN** the Controller leaves the operation outcome unknown
- **AND** it does not blindly resend the mutation

#### Scenario: Reconciliation returns a receipt for another workspace

- **GIVEN** a pending command belongs to workspace account A
- **WHEN** reconciliation returns an otherwise well-formed receipt naming workspace account B
- **THEN** the Controller rejects the receipt as an identity mismatch
- **AND** the pending effect ownership is retained for further/manual reconciliation

### Requirement: Legacy migration journal remains a single authority during mutation extraction

During migration, Controller membership mutations MAY reuse the existing durable member-switch control/command-receipt tables through a compatibility adapter, but SHALL NOT create a second mutable journal for the same operation. Controller mutation rows SHALL use a distinct kind understood by both the Controller adapter and legacy member-switch admission. An active or pending Controller mutation SHALL block competing legacy membership work. A structurally valid terminal Controller mutation with released active scope and no pending action SHALL be treated as inert history and SHALL NOT permanently block future work.

#### Scenario: Legacy process sees a pending Controller mutation

- **WHEN** legacy member-switch admission scans the shared journal
- **THEN** it reports the Controller mutation as retained/blocking work
- **AND** it does not start a competing membership effect

#### Scenario: Legacy process sees settled Controller history

- **GIVEN** the Controller mutation is terminal, has no pending action and has released the shared active scope
- **WHEN** legacy admission scans the journal
- **THEN** that row does not block creation of later membership work

### Requirement: Mutation extraction does not prematurely expose an unauthenticated mutation API

The internal add/remove/switch command service and effect/journal ports MAY exist before standalone packaging, but the Controller HTTP router SHALL remain read-only until service authentication and mutation qualification are completed. Mutation extraction SHALL NOT by itself activate a production membership-effect adapter or expose POST/PUT/PATCH/DELETE membership routes.

#### Scenario: Slice-7 Controller router is inspected

- **WHEN** the extracted Controller HTTP router is enumerated after mutation command extraction
- **THEN** it still exposes only the previously qualified GET/HEAD read surface
- **AND** mutation commands are reachable only as internal service contracts, not network operations
