## ADDED Requirements

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
