# member-switch-commands Specification

## Purpose
Define automatic member-switch dispatch evidence and distinguish removal intent
from authoritative confirmation while preserving durable no-replay accounting.
Define bounded canary execution and durable managed removal telemetry.

## Requirements

### Requirement: Weekly evidence remains valid at automatic dispatch

The automatic controller SHALL reassess the same decision Weekly evidence with
the current clock after asynchronous admission and quota-accounting work and
immediately before invoking Companion start. The evidence SHALL still be fresh,
exhausted, and before its reset deadline for the exact evaluated member.
Expired or otherwise unknown evidence SHALL prevent Companion start and use the
existing authoritative local non-effect cleanup. It SHALL NOT trigger an
automatic retry or overwrite retained historical snapshots.

#### Scenario: Admission waits beyond the freshness horizon
- **GIVEN** fresh exhausted Weekly evidence admitted an automatic evaluation
- **WHEN** asynchronous start preparation reaches the freshness horizon
- **THEN** the controller does not invoke Companion start
- **AND** the child scope closes and its proven non-effect quota is released

#### Scenario: Reset deadline passes during quota accounting
- **GIVEN** the decision evidence is still within the freshness horizon
- **WHEN** its Weekly reset deadline passes during the final quota write
- **THEN** the controller does not invoke Companion start
- **AND** restarting the controller does not dispatch the rejected operation

#### Scenario: Evidence is still valid after preparation
- **GIVEN** the final decision evidence remains fresh and exhausted
- **AND** its reset deadline has not passed
- **WHEN** all existing identity, provenance, snapshot, and quota gates pass
- **THEN** the existing durable child may issue its single Companion start

### Requirement: Outgoing identity is not removal confirmation

The controller SHALL require exact outgoing email/user identity and the qualified
Companion's durable `verifying_removal` / `outgoing_workspace_absence_observed`
trace before promoting an unknown removal effect to confirmed. The trace entry
SHALL be an operation-stage observation, without action/status command fields.
Removal intent, generic failure, invitation transmission, and missing or
truncated evidence SHALL NOT be substituted for this confirmation. Unknown
effects SHALL remain reserved beyond the rolling quota windows until resolved.

#### Scenario: Removing operation already names the outgoing member
- **GIVEN** a running or failed operation includes the exact outgoing identity
- **AND** it has no authoritative outgoing-absence observation
- **WHEN** the controller reconciles it, including after eight days
- **THEN** removal remains unknown and occupies the local quota
- **AND** no remove request is replayed

#### Scenario: Authoritative outgoing absence is retained
- **GIVEN** the operation identifies the exact outgoing member
- **AND** its durable trace records successful outgoing-workspace absence observation
- **WHEN** the controller reconciles the operation
- **THEN** removal is recorded as confirmed independently of invitation completion

### Requirement: Canary is one durable workflow

A start request MAY explicitly select canary execution and SHALL default to
ordinary manual behavior when omitted. A canary SHALL require a durable client
flow receipt. At most one canary client flow SHALL bind in the retained operation
store. Its binding SHALL survive completion, release and process reconstruction.
Duplicate starts SHALL only return the existing receipt, never launch work again.
Changing canary mode on an existing client flow SHALL be rejected.
Canary transport SHALL use a dedicated `/canary-operations` endpoint with the
existing managed-write protocol. A rejected/unsupported canary endpoint SHALL
NOT fall back to ordinary `/operations`; each endpoint SHALL reject a mismatched
body mode. An older Companion must reject, rather than ignore, the canary mode.
The first canary binding SHALL advance the local receipt schema so an older
runtime cannot read, rewrite, and silently discard the spent canary budget.

#### Scenario: A different canary is requested after release
- **GIVEN** a canary client flow is durably recorded and released
- **WHEN** another client flow requests canary mode
- **THEN** it is rejected before membership work is scheduled

#### Scenario: Old Companion receives a canary request
- **WHEN** the dedicated canary endpoint is unavailable
- **THEN** the backend does not retry on the ordinary operations endpoint
- **AND** no unguarded replacement is started

### Requirement: Canary claims precede each real membership effect

The Companion SHALL persist at most one remove claim and at most one invite claim
for its bound canary before calling the corresponding browser mutation. Failed
or ambiguous effects SHALL NOT refund claims. Invite admission SHALL require a
remove claim and authoritative removal plus outgoing-workspace absence
verification for the same operation. A persistence error, missing receipt, or
duplicate claim SHALL fail closed before that mutation. Restart SHALL not resume
an interrupted canary or grant another claim. No in-memory-only canary is allowed.
Canary removal verification SHALL NOT retry DELETE, including a definitive
`404/member_identity_missing` response that permits retry in manual mode.

#### Scenario: Delete response is lost
- **GIVEN** the remove claim was committed before DELETE
- **WHEN** its response is lost and the service restarts
- **THEN** DELETE is not replayed
- **AND** invite remains blocked unless authoritative outgoing absence was recorded

#### Scenario: Invitation persistence fails
- **GIVEN** removal and outgoing absence have been confirmed
- **WHEN** saving the invite claim fails
- **THEN** the invite browser call is not executed

#### Scenario: Delete reports a missing identity while the member remains visible
- **WHEN** a canary DELETE returns `404/member_identity_missing`
- **AND** inspection still observes the outgoing member
- **THEN** verification fails without another DELETE or an invitation

### Requirement: Managed removal preserves typed telemetry

The managed operation SHALL normalize and durably retain the delete response with
the existing bounded recursive sanitizer, preserving primitive types, absence,
null and capture uncertainty. Subsequent operation updates SHALL retain that
observation. The backend SHALL project it separately from invitation evidence.
Capture failure SHALL NOT create replay authority.

#### Scenario: Later invitation update follows a delete response
- **GIVEN** a managed delete returned sanitized response telemetry
- **WHEN** invitation progress and process reconstruction occur
- **THEN** the same remove observation remains available separately from invite telemetry

### Requirement: Automatic dispatch requires current externally verified runtime evidence

Automatic dispatch SHALL require an Ed25519-signed host observation from an
operator-provisioned public key, bound to the exact configured Companion endpoint
and qualified release tuple. Evidence SHALL include the listener process identity,
start identity and executable identity and SHALL expire within 30 seconds of its
observation. Missing, malformed, future, expired, incorrectly signed or mismatched
evidence SHALL block dispatch. The signature and freshness SHALL be checked after
admission and quota persistence immediately before the Companion start request.
Persisted display flags SHALL NOT substitute for this check. Automatic starts
SHALL select the dedicated canary endpoint and require its advertised capability.

#### Scenario: Evidence expires during admission
- **GIVEN** a runtime observation was valid before asynchronous admission
- **WHEN** it is expired at the final dispatch boundary
- **THEN** no Companion start is sent and the local quota request is recorded as non-effect

#### Scenario: Caller supplies the qualified tuple without host evidence
- **WHEN** an automatic start supplies the expected release constants
- **AND** no signed current host observation is available
- **THEN** the start is blocked

### Requirement: Server scheduling is default off and scoped to one Q3 evaluation

The application SHALL own scheduler start/stop. Without an operator-provisioned
enabled canary plan, scheduling SHALL perform no database or external work. An
enabled plan SHALL bind one immutable evaluation UUID, workspace, outgoing account
identity and membership epoch. Each tick SHALL run under the existing leader gate,
serialize local execution, require enabled workspace intent and fresh host evidence,
and obtain fresh P1 evidence before P2 reset resolution and P3 admission. Reset
request and quota identities SHALL remain stable across ticks and restart. Existing
controller work SHALL be reconciled without another evaluation or reset attempt.
The scheduler SHALL recheck plan and workspace intent before reset and dispatch.
Shutdown SHALL cancel and await its owned loop; uncertainty SHALL remain durable.

#### Scenario: No enabled plan exists
- **WHEN** the application starts and the scheduler ticks
- **THEN** no reset, membership, Usage fetch or database operation is initiated

#### Scenario: A scheduler restarts after a controller exists
- **WHEN** the same planned evaluation is encountered again
- **THEN** it is reconciled through its durable controller without creating new effect authority

### Requirement: Canary artifact qualification identifies the exact uncommitted source

The 2.11.48-canary.1 source candidate SHALL be qualified only by the registered
exact version, published executable SHA-256 and canonical source-file manifest
SHA-256. An uncommitted candidate SHALL carry no owning Git commit. A missing or
altered source digest, binary digest, or invented owning commit SHALL fail closed.
Historical P4 version/hash/owning-commit qualification SHALL remain a separate
tuple and SHALL NOT certify the new candidate. Artifact qualification SHALL NOT
substitute for a current signed host observation, Canary capability, enabled
operator plan, Weekly/reset/quota evidence or the single-use effect budget.

#### Scenario: A source digest is substituted on the new binary
- **GIVEN** the registered Canary executable hash
- **WHEN** the asserted source-manifest hash differs
- **THEN** runtime attestation and automatic dispatch reject the candidate

#### Scenario: A historical owning commit is assigned to the candidate
- **WHEN** the new candidate carries the old P4 owning commit
- **THEN** the provenance assertion is rejected

### Requirement: Matched OFF deployment retains durable effect state
The operator tooling SHALL admit the exact built backend image and its canonical
source manifest before releasing its candidate-specific first-start gate. An
inherited image tree label SHALL NOT substitute for the uncommitted source
manifest. Gate release SHALL be atomic and prove the same PID1 epoch and network
namespace across application start. Ambiguous release SHALL stop the candidate
before predecessor recovery. Both backend and Companion durable effect records
SHALL be preserved, and no canary plan SHALL be enabled by OFF deployment.

#### Scenario: Candidate provenance differs
- **WHEN** image or canonical source identity differs from the sealed packet
- **THEN** candidate gate release is denied

#### Scenario: OFF deployment completes
- **WHEN** the matched pair starts
- **THEN** the retained stores remain intact and no automatic effect is authorized

### Requirement: Host signer keeps the private key outside backend mounts
The host signer SHALL retain its Ed25519 private key in a private host directory.
The backend SHALL receive only a read-only observation directory with the public
key and current signed host observations. Signing SHALL bind the exact deployed
Companion executable and registered source identity. A failed signer or stale
observation SHALL block dispatch without resetting any effect budget.
The background signer SHALL use a dedicated installed runtime outside the
development checkout. Qualification SHALL verify automatic observation renewal
through the actual LaunchAgent over longer than one observation validity period.

#### Scenario: Companion binary changes
- **WHEN** the running mapped executable differs from the qualified artifact
- **THEN** the signer rejects it and no fresh authorization observation is emitted

#### Scenario: Background signer cannot start
- **WHEN** an operating-system access prompt prevents the signer from starting
- **THEN** stale observations block dispatch, and qualification does not pass until
  the installed background service renews independently without that prompt

### Requirement: Current OFF operations preserve the qualified deployment
The current OFF operations entrypoint SHALL pin the qualified PostgreSQL identity,
schema, lane storage, backend image and Companion artifact. Before lane mutation
it SHALL require rotation OFF, no active effects and an unchanged receipt store.
Recreation SHALL use the shared operation lock and a fresh first-start gate
namespace, preserve the predecessor and its sentinel, and verify the stopped
candidate configuration before fencing the predecessor. Failed or interrupted
recreation SHALL prove the candidate stopped with restart disabled before
recovering the predecessor. Unproven recovery SHALL retain a needs-review lock.
The recreation and recovery transaction SHALL be qualified in isolation before
its production entrypoint is used.

#### Scenario: Database or OFF state differs
- **WHEN** a pinned database, schema, artifact or OFF-state check fails
- **THEN** lane recreation performs no predecessor mutation

#### Scenario: Candidate start or gate release fails
- **WHEN** recreation cannot prove successful startup
- **THEN** recovery disables candidate restart and proves it stopped before
  restoring the retained predecessor without changing durable effect records

### Requirement: Non-canary diagnostics have no activation authority
A non-canary diagnostic runner SHALL exclude reset redemption, member removal,
invitation, operation start, enabled intent, plan publication and quota reservation.
It SHALL compare sanitized numeric upstream usage fields with production parsing
and classification without persisting usage. It SHALL use read-only database
transactions and allow only Companion catalog, admission, membership observation
and preview endpoints. Independent checks SHALL report PASS, FAIL, ERROR or
SKIPPED separately; an absent prerequisite SHALL NOT be converted into success.
The resulting report SHALL always declare that it grants no activation authority.

#### Scenario: Final retention lacks 5H input and absence evidence
- **WHEN** a fresh actual usage response cannot produce final retention inputs
- **THEN** the report retains the failure while independently observable later
  checks may still run without an effect or any activation authorization

#### Scenario: Diagnostic attempts an effect endpoint
- **WHEN** the runner attempts a Companion operation or participant command
- **THEN** its allowlist rejects the request before transport

### Requirement: Optional five-hour evidence is bound to one fetch
The system SHALL classify base 5H availability from one successful identity-bound Usage response as observed, not_provided, or unknown without inferring it from subscription labels. Only an unambiguous Weekly-only response with null or omitted sibling SHALL establish not_provided. Failed fetches, missing rate-limit evidence, malformed or ambiguous windows SHALL NOT establish absence.

#### Scenario: Successful Weekly-only response
- **GIVEN** one fresh successful identity-bound fetch returns one classified Weekly window and no sibling window
- **WHEN** final usage retention is prepared
- **THEN** the system SHALL retain Weekly and explicit same-fetch 5H absence evidence without fabricating a 5H value
- **AND** Weekly validation, reset-first coordination, quotas and effect authorization SHALL remain required

#### Scenario: Missing evidence is unknown
- **GIVEN** a receipt has no 5H window and no explicit valid absence evidence
- **WHEN** final usage retention is prepared
- **THEN** retention SHALL remain blocked

### Requirement: Optional five-hour history preserves epoch integrity
The system SHALL persist versioned absence provenance with a Weekly-only epoch and validate its identity, fetch, observation timestamp, and expected window set on retention and recovery. It SHALL continue to read legacy complete 5H/Weekly pairs and SHALL NOT reinterpret incomplete legacy epochs as valid absence. Retries SHALL preserve immutable evidence and SHALL NOT replay effects.

#### Scenario: Recover committed Weekly-only evidence
- **GIVEN** a valid Weekly-only epoch was committed before controller state publication
- **WHEN** the controller resumes
- **THEN** it SHALL recover that same immutable epoch without rewriting evidence or replaying effects

#### Scenario: Incomplete legacy pair
- **GIVEN** a legacy epoch contains only a Weekly row without versioned absence provenance
- **WHEN** recovery is attempted
- **THEN** recovery SHALL reject the incomplete epoch

### Requirement: Operator distinguishes absent five-hour evidence
Operator API and UI SHALL distinguish not_provided from unknown or missing 5H evidence for the current member and retained history, with no invented usage percentage. Absence evidence SHALL NOT be projected onto a replacement member.

#### Scenario: Display Weekly-only retained history
- **GIVEN** a validated Weekly-only epoch records not_provided
- **WHEN** an operator reads its history
- **THEN** the API SHALL expose not_provided and the UI SHALL display 미제공 without a percentage

### Requirement: Legacy provenance dispatch preserves complete-pair compatibility
The repository SHALL accept complete legacy 5H/Weekly pairs with identical nonempty opaque provenance, including unversioned JSON objects, subject to existing row identity and immutable-evidence checks. Explicit unsupported or malformed versions and recognizable incomplete versioned provenance SHALL fail closed rather than use the opaque fallback. Legacy provenance SHALL NOT prove five-hour absence or admit an incomplete epoch.

#### Scenario: Opaque JSON object on a complete legacy pair
- **GIVEN** a complete legacy pair with identical unversioned opaque JSON-object provenance and valid existing row identity
- **WHEN** retention is retried or the epoch is recovered
- **THEN** the same original rows SHALL be returned without rewriting provenance
- **AND** the retained five-hour state SHALL be observed

#### Scenario: Incomplete or versioned evidence cannot use legacy fallback
- **GIVEN** a single legacy Weekly row, an unsupported explicit version, or recognizable incomplete versioned provenance
- **WHEN** retention or recovery is attempted
- **THEN** it SHALL be rejected without rewriting evidence or creating effect authority

### Requirement: Retained five-hour uncertainty remains visible with raw values
The operator UI SHALL render the full retained five-hour state. When the state is unknown, the five-hour history block SHALL explicitly display 미확인 even if a raw numeric row exists. Retained raw values MAY remain visible but SHALL be labeled as unverified original evidence rather than validated final usage. The not_provided state SHALL remain distinct and SHALL NOT invent a percentage. Existing original/effective reset separation and reset invalidation notices SHALL remain visible.

#### Scenario: Unknown five-hour evidence retains a numeric row
- **GIVEN** an incomplete legacy 5H-only epoch or an identity-invalid v2 pair whose API history state is unknown
- **WHEN** the actual history component renders the supplied raw five-hour row
- **THEN** the five-hour block SHALL display 미확인 and distinguish retained raw values from validated evidence

#### Scenario: Valid and absent controls retain their meaning
- **GIVEN** a validated complete pair or validated Weekly-only epoch
- **WHEN** history is displayed
- **THEN** observed evidence SHALL retain its normal rendering and not_provided SHALL display 미제공 without a fabricated percentage

### Requirement: Manifest-bound OFF release admission
The OFF deployment tool SHALL admit only the qualified immutable candidate image and its exact source manifest/content digest without assigning the uncommitted source to an inherited owning commit. Before production replacement it SHALL verify current PostgreSQL-copy compatibility and the exact operation implementation's successful and failure-boundary qualification. It SHALL preserve Stable, Companion, shared PostgreSQL identity and schema, durable control/receipt/rotation state and the absence of enabled intent and canary plan.

#### Scenario: Candidate identity is different from historical gate pins
- **WHEN** the qualified image has manifest-owned source rather than the historical gate's owning revision/tree
- **THEN** admission verifies the exact image configuration and full manifest digests, rejects any mismatch, and does not fabricate or truncate a Git identity.

### Requirement: OFF replacement and retained predecessor recovery
The operation SHALL use a private one-attempt journal and a unique gate namespace, prevent application listening before publication, and prove release in the same PID1 epoch/network namespace. A successful cutover SHALL retain the immediate predecessor stopped with restart disabled and its networks disconnected. Rollback SHALL prove the candidate stopped before revoking its gate or restoring the predecessor's exact network/configuration ownership. Unproven recovery SHALL retain a needs-review lock and journal rather than starting a second lane.

#### Scenario: Failure after gate publication
- **WHEN** a candidate fails verification after publication
- **THEN** the transaction disables restart, proves stop, revokes only its own gate, and restores the reviewed immediate predecessor without restoring or migrating production PostgreSQL.

#### Scenario: Successful OFF deployment
- **WHEN** the new Beta is ready and all protected-state checks pass
- **THEN** the canonical Beta lane uses the exact candidate and configured restart policy, the predecessor is retained fenced, and rotation remains OFF without reset, remove, invite or canary execution.

### Requirement: Rotation reset admission is checked at the consume boundary
The central reset executor SHALL invoke a supplied final admission guard after awaited credit discovery and durable pinning and immediately before consume transport. Rotation SHALL require the same enabled, unexpired plan, enabled workspace intent, exact account/member identity, fresh exhausted Weekly evidence and current qualified runtime evidence at this boundary. Rejection SHALL send no consume or membership start and SHALL NOT erase a durable pin or grant another evaluation. Ordinary non-rotation callers without this guard SHALL retain the existing serialized redemption contract.

#### Scenario: Authority changes during awaited credit discovery or pinning
- **WHEN** the plan is revoked or expires, workspace intent is disabled, or required identity/freshness becomes invalid before consume
- **THEN** the final guard rejects without a consume request and retains any existing no-replay evidence

### Requirement: Interrupted pre-effect worker state is explicit attention
An existing planned controller that cannot safely advance without fresh pre-effect evaluation SHALL transition to durable needs_attention through the worker recovery path. It SHALL report a specific operator-recovery reason, retain its binding, immutable snapshots and conservative quota ownership, and SHALL NOT repeat reset or create/start a membership operation. Existing uncertain-effect reconciliation SHALL remain distinct and SHALL NOT be converted to proven non-effect.

#### Scenario: Worker resumes after snapshot or preview but before start
- **WHEN** the reconstructed worker encounters the same interrupted pre-effect controller
- **THEN** it exposes needs_attention and an operator blocker without another reset/start or indefinite foundation_evaluating status

### Requirement: Operator wire responses agree with persisted state and client schema
Successful intent updates SHALL return the committed enabled value and CAS version so the next sequential update may use that version. The frontend SHALL parse the actual canonical backend operator aliases count24H, limit24H, count168H and limit168H, including non-null foundation counts. Default-OFF status SHALL remain readable without an enabled plan or controller. Tests SHALL exercise actual backend serialization rather than rely only on hand-authored component data.

#### Scenario: Existing intent is toggled twice
- **WHEN** an authorized caller saves ON, then OFF, then ON using each returned version
- **THEN** responses and fresh reads agree and each valid sequential update succeeds

#### Scenario: Backend returns a default-OFF workspace
- **WHEN** the actual frontend API client validates that backend response
- **THEN** it accepts the canonical quota aliases and displays the workspace instead of invalid_response_schema

### Requirement: Rotation scheduler participates in ambient test isolation
The application lifespan rotation scheduler SHALL be classified in the test harness background-loop seam and replaced with a no-op for ambient application tests. Dedicated scheduler tests SHALL still exercise the real scheduler directly. Rotation qualification SHALL include the completeness check so adding an unclassified scheduler cannot silently start it during unrelated tests.

#### Scenario: Ambient test lifespan starts
- **WHEN** the test harness constructs the application background schedulers
- **THEN** rotation uses the classified no-op builder while direct scheduler regression tests remain active
