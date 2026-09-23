## ADDED Requirements

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
