## ADDED Requirements

### Requirement: Automatic replacement reuses durable member-switch ownership

Any future usage-driven Business member replacement SHALL acquire the same server-owned durable member-switch authority used by explicit member work before crossing a membership effect boundary. Automatic eligibility SHALL NOT override an unresolved manual operation, an unresolved prior automatic effect, exact owner/member identity checks, or Companion operation receipts. The workspace owner SHALL never be a replacement target merely because the owner also exists in the OAuth/account catalog.

#### Scenario: Manual effect remains unresolved
- **GIVEN** the workspace has an unresolved manual member-switch or participant command
- **WHEN** usage-driven rotation otherwise becomes eligible
- **THEN** automatic replacement is not admitted
- **AND** the existing operation remains authoritative

### Requirement: Internal replacement quota is rolling and conservative

Before a new replacement operation may cross its first membership-effect boundary, the system SHALL enforce per-workspace rolling internal limits of at most three effective operations in the immediately preceding 24 hours and at most seven effective operations in the immediately preceding 168 hours. The third and seventh operations are allowed; a prospective fourth or eighth operation is blocked.

For admission accounting, an operation whose removal/invite effect may have crossed an external boundary SHALL remain counted/reserved until authoritative evidence proves a safe non-effect. The ledger SHALL keep request attempts, confirmed/unknown effects, and business-level completion distinct. A confirmed removal followed by a failed invite SHALL NOT be erased as zero activity. An ambiguous/lost response SHALL NOT release a quota reservation merely because the immediate reply is absent. Counts from incomplete local history SHALL be labeled observed/local counts and MUST NOT be represented as the authoritative OpenAI replacement count.

An observed undocumented upstream threshold or ordinal SHALL remain telemetry until its action, scope, window, and semantics are verified. Such telemetry SHALL NOT automatically loosen the 3/7 internal policy. Billing telemetry, including `billed_seat_delta`, SHALL NOT participate in replacement-count calculation.

#### Scenario: Seventh rolling-week operation is admitted
- **GIVEN** the workspace has six effective replacement operations in the preceding 168 hours
- **AND** fewer than three effective operations in the preceding 24 hours
- **WHEN** one new operation is reserved
- **THEN** the resulting rolling-week count of seven is allowed

#### Scenario: Eighth rolling-week operation is blocked
- **GIVEN** the workspace already has seven effective replacement operations in the preceding 168 hours
- **WHEN** another operation requests admission
- **THEN** it is blocked before any remove or invite mutation

#### Scenario: Lost removal reply continues to occupy quota
- **GIVEN** a replacement crossed the removal request boundary
- **AND** its immediate response was lost or malformed
- **WHEN** rolling quota is calculated before authoritative reconciliation proves a non-effect
- **THEN** the operation remains counted/reserved
- **AND** another operation cannot reclaim that slot from reply ambiguity alone

### Requirement: Removed-member Usage history remains immutable evidence

Before an admitted removal is sent, the system SHALL durably retain the outgoing member's latest classified Weekly observation and either its same-fetch classified 5H observation or explicit versioned 5H absence evidence, including raw used percentage, window duration, original reset timestamp, observation timestamp, source/provenance, workspace/member identity sufficient for exact internal correlation, and the membership epoch or equivalent boundary needed to prevent later account reuse from overwriting that historical membership record. Failure to persist the required final snapshot SHALL block the removal.

A historical Reset-schedule clear action SHALL NOT delete the original snapshot, mutate its original usage/reset values, consume a reset credit, or clear member-change/effect history. It SHALL create durable invalidation evidence with a fixed cutoff and SHALL affect only the effective/display Reset schedule of eligible historical snapshots observed at or before that cutoff. Snapshots created after the cutoff SHALL remain unaffected.

#### Scenario: Removal preserves final 5H and Weekly facts
- **GIVEN** an outgoing member has fresh retained 5H and Weekly observations
- **WHEN** the system is about to authorize removal
- **THEN** both final observations are durably committed before the remove request
- **AND** later removal/account reuse cannot overwrite those original facts

#### Scenario: Bulk historical Reset cleanup preserves the original snapshot
- **GIVEN** a removed-member snapshot contains an original Reset timestamp
- **WHEN** the operator clears historical Reset schedules with cutoff T
- **THEN** the original timestamp and Usage values remain stored as evidence
- **AND** the effective Reset schedule is hidden/invalidated only for eligible snapshots observed at or before T
- **AND** no reset credit or member-change counter is altered

#### Scenario: Weekly-only history and restart recovery
- **GIVEN** a successful identity-bound Weekly-only fetch proves 5H not_provided
- **WHEN** final retention commits the membership epoch
- **THEN** it SHALL persist one Weekly row with versioned identity-bound absence provenance
- **AND** recovery SHALL validate provenance and the expected row set before reusing that epoch
- **AND** incomplete legacy pairs SHALL NOT be reinterpreted as absence


### Requirement: Remove and invite response telemetry preserves typed uncertainty

The trusted Companion SHALL expose separately sanitized response observations for owner-side member removal and invitation. Sanitized JSON primitive values SHALL preserve their JSON types. The observation envelope SHALL distinguish an absent field, a present JSON `null`, an empty response body, JSON parse failure, no response received, and transport failure. It SHALL NOT collapse parse failure to JSON null or coerce numbers/booleans to strings.

Sanitization SHALL recursively inspect object keys, dynamic keys, arrays, and nested values and SHALL refuse raw response bodies, HAR content, authorization/session/cookie/CSRF material, email addresses, raw user/member/workspace/account/invitation/payment identifiers, or arbitrary unrestricted strings. Failure to capture or sanitize telemetry SHALL NOT authorize replay of a remove or invite mutation. Sending an invitation SHALL NOT be represented as join completion; join remains a separately observed effect.

#### Scenario: Primitive JSON types survive sanitization
- **WHEN** a response contains a safe telemetry number, boolean, explicit null, and an absent comparison field
- **THEN** the sanitized observation preserves the number as numeric, the boolean as boolean, the explicit null as null, and the missing field as absent

#### Scenario: Parse failure is not JSON null
- **WHEN** an HTTP response arrives but its body cannot be parsed as the expected JSON object
- **THEN** the observation records a parse-failure outcome distinct from JSON null and an empty body
- **AND** the membership mutation is not replayed to improve telemetry

#### Scenario: Invite sent is not member joined
- **WHEN** the owner-side invite request is confirmed sent
- **THEN** the operation records the invite effect separately
- **AND** completion still requires the authoritative membership/join evidence defined by the member-switch flow

### Requirement: Automatic controller proves the P4 telemetry provenance before mutation

The automatic rotation controller SHALL require an explicit trusted Companion
provenance assertion that identifies the qualified typed-telemetry contract,
version, binary digest, and operations source before it may cross the existing
durable member-switch start boundary. The controller SHALL NOT infer P4 support
from the presence or absence of optional response fields. Unknown, missing, or
mismatched provenance SHALL fail closed before a membership mutation.

#### Scenario: Typed fields are absent but provenance is unknown
- **GIVEN** automatic rotation has otherwise reached `admission_ready`
- **AND** no trusted P4 provenance assertion is available
- **WHEN** the controller reaches its pre-effect gate
- **THEN** it enters an attention state
- **AND** no member-switch start command is claimed or executed

### Requirement: Automatic and manual replacement share one durable effect scope

An automatic rotation MAY retain restart state outside the global member-switch
scope, but its child replacement run SHALL acquire the same durable global
member-switch scope and command claim used by manual replacement. A retained
controller record SHALL NOT itself authorize a mutation. A malformed controller
record SHALL block admission for review.

#### Scenario: Manual work wins the race before automatic start
- **GIVEN** an automatic evaluation has retained only pre-effect controller state
- **AND** a manual member-switch run acquires the durable global effect scope
- **WHEN** the automatic controller tries to create its child run
- **THEN** automatic membership mutation remains blocked
- **AND** the manual run remains authoritative
