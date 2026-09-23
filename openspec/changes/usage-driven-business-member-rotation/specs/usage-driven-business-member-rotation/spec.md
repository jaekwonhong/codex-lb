## ADDED Requirements

### Requirement: Usage-driven Business member rotation is default-off and fail-closed

Usage-driven Business member rotation SHALL be disabled by default. Before any automatic membership mutation is admitted, the system SHALL have exact current workspace/member identity, confirmed fresh Weekly exhaustion, completed reset-credit resolution, passing rolling replacement quota, no conflicting/unresolved member effect, and a durably committed outgoing final Usage snapshot. An unknown prerequisite SHALL fail closed and SHALL NOT be converted to eligibility.

The foundation implementation and its parallel epics SHALL NOT perform live reset-credit or membership mutations for qualification. Automatic member effects may be connected only after the foundation changes have been integrated and independently reviewed.

#### Scenario: One prerequisite is unknown
- **GIVEN** all but one automatic-replacement prerequisite are confirmed
- **AND** the remaining prerequisite is unknown or stale
- **WHEN** automatic eligibility is evaluated
- **THEN** no member removal or invitation is authorized

### Requirement: Reset opportunity precedes replacement

Confirmed fresh Weekly exhaustion SHALL trigger reset-credit resolution before replacement admission. When one applicable reset credit is legitimately redeemed and bounded fresh Weekly reconciliation proves usage recovered, the member SHALL remain in the workspace and the replacement operation SHALL end without removal. Rotation SHALL NOT perform a replacement merely to finish an end-to-end test after usage has recovered.

#### Scenario: Reset restores Weekly usage
- **GIVEN** an exhausted member has an applicable reset credit
- **WHEN** one authorized redemption is followed by fresh evidence that the actual Weekly window is no longer exhausted
- **THEN** replacement is cancelled/ended before any membership mutation

### Requirement: Replacement effects remain a no-replay state machine

The later automatic controller SHALL treat reset redemption, remove, invite, and join/authoritative membership confirmation as distinct effect boundaries. Lost replies, process restarts, Companion restarts, and telemetry-capture failures SHALL NOT authorize repeating an effect-bearing request whose outcome may be unknown. Read-only reconciliation SHALL be preferred whenever an effect may already have happened.

#### Scenario: Process restarts after an uncertain invitation
- **GIVEN** an invitation request may have crossed its external effect boundary but no authoritative receipt was returned
- **WHEN** the controller restarts
- **THEN** it restores the unresolved durable operation and performs read-only reconciliation
- **AND** it does not send a second invitation merely because local execution restarted

The controller SHALL durably retain the evaluation identity, exact workspace
and outgoing/incoming identities, G1 admission/reset/quota references, final
snapshot commit identity, member-switch run/operation identity, remove and
invite reconciliation states, and terminal/attention reason. A restart after a
durable member-switch start claim SHALL use receipt/read-only reconciliation and
SHALL NOT claim a new start merely because the prior response was lost.

#### Scenario: Final Usage snapshot committed before process restart
- **GIVEN** the exact outgoing Weekly snapshot epoch with same-fetch 5H observation or versioned absence evidence was durably committed
- **AND** the process restarted before member-switch start
- **WHEN** the controller resumes the same evaluation and membership epoch
- **THEN** the immutable P3 snapshot is reused idempotently
- **AND** a conflicting overwrite is not created

### Requirement: Live qualification is bounded to operational necessity

After non-destructive qualification and independent review, the final live member-change canary SHALL be limited to at most one legitimate operational replacement. A remove response-capture failure SHALL NOT authorize another remove, and an invite response-capture failure SHALL NOT authorize another invite. A reset-credit test and a member-change test are separate: if a legitimate reset-credit redemption recovers usage, no artificial membership change SHALL be introduced solely to exercise the replacement path.

#### Scenario: Reset ends the final canary before replacement
- **GIVEN** the final candidate is being qualified on a genuinely exhausted operational member
- **WHEN** its legitimate reset credit restores Weekly usage
- **THEN** the canary records the reset path as qualified to that point
- **AND** it does not remove another member just to test replacement

### Requirement: Operator controls express intent without carrying effect authority

The Accounts member-management surface SHALL expose automatic member rotation as a workspace-scoped setting that is disabled by default. Changing the setting SHALL persist operator intent only. Loading, focusing, navigating to, reconnecting to, restoring browser state for, or polling the operator surface SHALL NOT initiate reset-credit redemption, member removal, invitation, OAuth, or any other membership effect.

The P6 operator API SHALL NOT expose an endpoint that directly dispatches automatic replacement effects. P5 remains responsible for effect orchestration and SHALL still pass its own durable admission and no-replay boundaries before acting on enabled intent.

#### Scenario: Status refresh while automatic rotation is enabled
- **GIVEN** automatic rotation intent is enabled for a workspace
- **WHEN** the operator page loads, receives focus, or performs a periodic status refresh
- **THEN** the UI performs read-only status observation
- **AND** it does not send reset, remove, invite, OAuth, or controller effect commands

### Requirement: Operator eligibility status is projected from authoritative read models

P6 SHALL display G1 `RotationFoundationReadModel` state and Weekly classification without recalculating eligibility from displayed Usage percentages, telemetry, or rounded values. It SHALL preserve the distinction between confirmed exhausted, available, and unknown Weekly evidence, including stale, elapsed-reset, and missing-evidence reasons. Reset-credit display SHALL distinguish resolution required, redemption in progress when the controller reports it, reconciliation pending, recovered, confirmed no redeemable credit, and unavailable/attention states.

P5-specific controller data SHALL enter P6 only through an additive read-only adapter. P6 SHALL remain usable when that adapter is absent and SHALL report the controller integration as unavailable rather than inventing eligibility from another data source.

#### Scenario: Rounded Weekly display could appear empty
- **GIVEN** the dashboard has a Usage percentage that could round to a boundary value
- **AND** G1 classifies the Weekly observation as unknown or available
- **WHEN** P6 renders the workspace
- **THEN** it displays the G1 classification
- **AND** it does not label the member exhausted from the rounded percentage

### Requirement: Internal rotation guard is labeled as local observed policy

P6 SHALL display the local rolling rotation guard as 24H observed count out of 3 and 7D observed count out of 7. These counts SHALL be described as internal/local policy evidence and SHALL NOT be represented as an OpenAI server limit. The UI SHALL disclose when local history coverage is incomplete and that member changes before local retention or outside this system may not be included.

#### Scenario: Local ledger has incomplete history
- **GIVEN** the local quota ledger observes 4 operations in its retained 7D window
- **AND** the ledger cannot prove complete coverage of external or pre-adoption changes
- **WHEN** the operator views quota history
- **THEN** the UI labels the count as locally observed
- **AND** it does not describe 4 as the authoritative number of OpenAI-side replacements

### Requirement: Historical member Usage preserves original evidence separately from effective reset display

P6 SHALL continue to expose retained final Weekly Usage and either retained 5H Usage or validated not_provided state for removed membership epochs. Missing legacy 5H rows SHALL remain unknown. When a historical reset schedule has been invalidated at a cutoff, the original `reset_at` SHALL remain visible as retained evidence while the effective reset display SHALL indicate that no current reset schedule applies. Historical reset invalidation SHALL NOT be described as resetting Usage, consuming a reset credit, mutating OpenAI state, or deleting rotation history.

#### Scenario: Historical reset schedule was invalidated
- **GIVEN** a removed member snapshot retains an original Weekly `reset_at`
- **AND** P3 marks that historical reset schedule invalid at a later cutoff
- **WHEN** P6 renders the removed-member history
- **THEN** it shows the original reset value
- **AND** it shows the effective reset schedule as unavailable or cleared
- **AND** it indicates that the original historical evidence remains retained

### Requirement: Attention states remain explicit and effect ambiguity is never a retry affordance

P6 SHALL surface `usage_unknown`, `reset_reconciliation_pending`, `reset_unavailable`, `invalid_evidence`, `quota_blocked`, unknown remove effect, unknown invite effect, and Companion capability/provenance mismatch as operator attention. An unknown remove or invite effect SHALL NOT be presented with a control that simply resends that effect. Invitation issued and authoritative membership confirmation SHALL be displayed as separate states.

The owner identity SHALL NOT be displayed as an automatic rotation candidate, including when an invalid upstream adapter snapshot reports it.

#### Scenario: Invite request crossed its effect boundary but join is unconfirmed
- **GIVEN** controller status says the invitation was issued
- **AND** authoritative membership confirmation is still false or unknown
- **WHEN** P6 renders the controller state
- **THEN** it reports the invitation as issued but membership as unconfirmed
- **AND** it does not offer an invite replay action

### Requirement: Release qualification is non-destructive and evidence driven

Before a G2 candidate may be considered ready for a live canary, qualification SHALL exercise the G1 public foundation boundary and durable repositories without sending a real reset-credit consume, member remove, invitation, join, OAuth operation, Companion installation, or lane deployment. The qualification matrix SHALL prove zero external member effect for unknown or stale Weekly evidence, reset-required/pending/unavailable/recovered outcomes, quota denial, invalid identity/evidence, and unavailable Companion capability/provenance. The matrix SHALL be expressed as reusable fixtures/protocols so the later P5 controller can be adapted to the same tests without P7 depending on P5 private implementation.

#### Scenario: A fail-closed foundation state is qualified
- **GIVEN** one foundation prerequisite resolves to a non-admission state
- **WHEN** the P7 failure-boundary harness evaluates that scenario
- **THEN** the observed external-effect counters remain unchanged
- **AND** the harness fails if its adapter emits a reset consume, remove, invite, join, or OAuth effect

### Requirement: Restart qualification proves no replay after an uncertain effect

P7 SHALL provide a restart/recovery protocol that can be adapted to the final controller for reset consume, remove, and invite effects. The protocol SHALL observe the actual effect-call count, cross one effect boundary, persist an operation/effect-specific durable receipt, simulate loss of its response and process reconstruction from durable state, and require post-restart authoritative reconciliation to read back that same receipt without issuing another effect. A replay-unsafe adapter or an adapter that returns a different/synthetic receipt SHALL fail the same harness so a passing result cannot be obtained merely by returning a synthetic success state.

#### Scenario: Invitation response is lost across restart
- **GIVEN** one invitation POST has crossed its effect boundary and its response is lost
- **WHEN** a reconstructed adapter reconciles the operation
- **THEN** the invitation POST count remains exactly one
- **AND** the reconstructed adapter and authoritative read expose the same durable operation/effect receipt

### Requirement: Release preflight binds exact candidate and Companion provenance

The final G2 deployment preflight SHALL fail closed unless evidence is bound to the exact target `workspace_account_id` and binds the exact candidate source SHA, package version, immutable image/package digest, exact P4 artifact hashes and candidate version/binary SHA, passing PostgreSQL gate, zero conflicting member/OAuth operations, expected immutable Stable and Beta digests before and after read-only preflight, automatic rotation default OFF, and an existing verified rollback artifact digest. P4 artifact ownership and its reconstructed source baseline SHALL be recorded and verified as distinct provenance fields. The post-migration PostgreSQL evidence SHALL additionally bind the exact container identity and start epoch, cluster system identifier, official beta.9 current/head revision, member-rotation local-extension contract/schema fingerprint, and one trusted database snapshot fingerprint. Migration, operation, feature-OFF, and matched beta.9 runtime evidence SHALL reference that admitted post-migration snapshot. Rollback evidence SHALL instead bind a verified catalog-preserving physical pre-migration PostgreSQL backup, its verified manifest identity, the source cluster system identifier, and a restore rehearsal at the predecessor official head that preserves the source system identifier and predecessor catalog representation; a logical `pg_dump`/`pg_restore` alone SHALL NOT satisfy rollback qualification when it rewrites the catalog representation consumed by the exact predecessor verifier. Rollback evidence SHALL NOT claim that beta.7 predecessors are compatible with the beta.9 database. The candidate Alembic head SHALL remain the official upstream beta.9 head; the four rotation tables SHALL be provisioned and validated as Beta-local extensions outside the Alembic lineage.

#### Scenario: P4 provenance is incomplete or mismatched
- **GIVEN** candidate source evidence is otherwise valid
- **WHEN** P4 artifact, binary, version, owning ops commit, or required contract evidence does not match the frozen qualification input
- **THEN** deployment preflight fails
- **AND** no automatic membership effect is authorized

### Requirement: Rollback preserves durable rotation evidence

Rollback qualification SHALL compare durable-state fingerprints across restoration of the verified catalog-preserving physical pre-migration database artifact. Quota/history, unresolved-effect receipts, removed-member Usage snapshots, reset-resolution state, existing OAuth/member records, both member-switch extension tables, and all four member-rotation extension tables SHALL be preserved exactly. Rolling back SHALL NOT convert an unresolved external effect into an absent/non-effect state. Before restore, the admitted post-migration beta.9 epoch SHALL include read-only migration-state probes from the exact predecessor Stable and Beta image/source/role identities proving `20260913_000000_add_oidc_provider_flow` is ahead/unknown to those beta.7 builds and therefore not rolling-compatible. The sealed pre-migration source snapshot SHALL itself bind to the verified physical backup manifest digest, record its PostgreSQL system identifier, and record count + data SHA-256 fingerprints for all six local extension tables. The restored database SHALL return to predecessor head `20260910_000000_request_logs_missing_cost_index`, preserve the same PostgreSQL system identifier and predecessor local-extension catalog/schema representation, reproduce those six-table data fingerprints exactly, restore the three legacy dashboard credential columns and their value fingerprint, and have the beta.9 `dashboard_legacy_credentials_retired` sentinel absent. Rollback preflight SHALL then require runtime-start probes for the exact predecessor Stable and Beta image/source/role identities against only that restored database; each probe SHALL prove the predecessor container `StartedAt` is strictly later than the restored database `StartedAt`, startup migrations are disabled, the predecessor remained running with zero restarts, reached `/health/ready` with HTTP 200, showed current/head at the predecessor official head, `needs_upgrade=false`, `is_ahead=false`, no unknown revisions, and retained the restored local-extension/snapshot fingerprints. Rollback SHALL use the verified physical pre-migration database restore rather than a logical dump/restore or an in-place beta.9 Alembic downgrade.

#### Scenario: Rollback loses an unresolved effect receipt
- **GIVEN** a pre-rollback snapshot contains an unresolved remove or invite receipt
- **WHEN** the rollback-state snapshot no longer contains the same durable evidence
- **THEN** rollback qualification fails
- **AND** the operation remains blocked from automatic retry

### Requirement: Beta.9 candidate first-start gate binds immutable runtime provenance

The beta.9 Q2 candidate SHALL use a new first-start gate namespace derived from the full admitted image digest and SHALL NOT consume the historical Q2 `592ace...` sentinel. Gate admission SHALL verify the exact immutable image digest, source SHA, source tree SHA, baked provenance labels, original image Entrypoint/Cmd, and original entrypoint bytes while the gated container uses exact `restart=no`. Sentinel publication SHALL be atomic and no-overwrite. A successful release SHALL prove the same PID1 starttime and network namespace exec the application. An outcome-unknown publication SHALL remain fail-closed unless the exact sentinel and same-process app exec are reconciled. Any reviewed post-stop revocation SHALL first prove the exact candidate is stopped with `restart=no` and that the revocation view shares the candidate runtime mount.

#### Scenario: Candidate gate publication outcome is ambiguous
- **GIVEN** the beta.9 gate publication command was invoked
- **WHEN** the final sentinel or same-process app exec cannot be authoritatively reconciled
- **THEN** qualification remains blocked for review
- **AND** the tooling does not guess that the gate is unpublished or revoke it

### Requirement: Feature enablement and live canary remain separate guarded steps

The candidate SHALL be deployable with automatic rotation disabled, and changing the feature setting SHALL NOT itself send a membership mutation. Feature ON SHALL remain outside P7 and SHALL only be allowed after final qualification. The final canary tooling SHALL distinguish read-only trace validation from explicit pre-effect authorization. Before each eventual remove or invite, G2 SHALL submit the already-recorded trace prefix and request authorization for that next effect; an already-consumed effect budget SHALL be denied even after capture failure or reconciliation. The canary guard SHALL permit at most one operational replacement workflow, one remove request, and one invitation request, and invite authorization SHALL require authoritative reconciliation of the single remove. Reset recovery SHALL permanently end the replacement path for that canary. A canary MAY stop after proving removal, and an invitation alone SHALL NOT be reported as successful join/membership confirmation.

#### Scenario: Capture failure does not reopen the mutation budget
- **GIVEN** the canary has already sent one remove or invitation request
- **WHEN** response capture fails and G2 asks to authorize the same effect again from the recorded trace prefix
- **THEN** the guard retains the consumed effect budget
- **AND** a second request of the same effect type is rejected

### Requirement: G2 operator projection is read-only and sourced from durable controller evidence

G2 SHALL connect the P6 operator snapshot seam to the durable P5 controller/run records without adding scheduler or effect authority. The projection SHALL preserve the P5-recorded foundation classification, Weekly reason, reset status, quota read-model fields, exact outgoing/incoming identities, P4 provenance status, remove/invite effect state, immutable 5H history, and authoritative membership-confirmation distinction. Reading the operator surface SHALL NOT create, resume, reconcile, or mutate a rotation controller, member-switch run, reset credit, membership, OAuth flow, or quota effect.

#### Scenario: Operator reads a retained controller while automatic rotation is disabled
- **GIVEN** a durable P5 controller exists for the workspace
- **AND** automatic rotation intent is disabled
- **WHEN** P6 reads the operator status
- **THEN** it projects the retained P5 facts without recalculating eligibility
- **AND** no external or durable effect boundary is crossed
