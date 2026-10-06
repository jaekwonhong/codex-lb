# responses-api-compat Delta

## ADDED Requirements

### Requirement: Relocation eligibility has a single decision point

The proxy MUST use one pure, transport-independent relocation verdict for direct HTTP streaming, downstream WebSocket, and the HTTP session bridge. Equal inputs MUST produce the same movable decision, body, and closed-vocabulary decline reason. Transcript-load failure MUST be treated as an absent transcript, and a declined verdict MUST preserve today's owner-bound behaviour.

#### Scenario: Transports agree

- **GIVEN** identical request state, anchor, evidence and durable transcript
- **WHEN** the stream path, the WebSocket path and the bridge path each evaluate relocation
- **THEN** all three produce the same verdict, the same body and the same decline reason

#### Scenario: File-pinned and turn-state-owned requests never relocate

- **GIVEN** a request carrying an input-file account pin or a turn-state owner
- **WHEN** relocation is evaluated after a definitive pre-dispatch rejection
- **THEN** the verdict declines with an ownership reason
- **AND** the request keeps today's owner-bound behaviour

#### Scenario: Visible output ends eligibility

- **GIVEN** the client has already received response output for this turn
- **WHEN** the upstream connection then fails
- **THEN** relocation declines
- **AND** the failure is surfaced as it is today

### Requirement: Anchored turns relocate on a rebuilt durable transcript

With definitive pre-dispatch owner failure and no visible response event, an anchored turn MAY relocate only from a complete durable parent chain. The rebuild MUST be oldest-first, bounded by turns, whole-transcript bytes, and items, preserve every client-sent item, drop only a matching reconstructed tail, and pass the strict account-neutral replay predicate. Missing, incomplete, unsafe, or unportable material MUST fail closed.

#### Scenario: A delta continuation survives its exhausted owner

- **GIVEN** a continuation carrying only `previous_response_id` and one new user turn
- **AND** the owner account answers with a usage-limit rejection before any response event
- **AND** the durable chain for that anchor is complete
- **WHEN** relocation is evaluated
- **THEN** the proxy rebuilds the conversation from the spool, drops the anchor, and dispatches to another account
- **AND** the client receives the response rather than an owner-unavailable failure

#### Scenario: A client full resend is not doubled

- **GIVEN** the client's input restates the whole conversation the chain reconstructs
- **WHEN** the join runs
- **THEN** the overlapping chain tail is discarded and the client's body is dispatched
- **AND** no turn appears twice

#### Scenario: A rolling window keeps everything

- **GIVEN** a four-turn chain and a client that sends the last exchange plus a new turn
- **WHEN** the join runs
- **THEN** the three earlier turns survive from the chain, the restated exchange survives from the client, and the new turn is last
- **AND** no item the client sent is missing

#### Scenario: A legal field difference does not double the conversation

- **GIVEN** a client restating the chain's turns in a form the wire allows but the projection normalizes — an assistant message without `status`, say
- **WHEN** the join computes the overlap
- **THEN** the restated turns are recognised and the chain's copies are discarded
- **AND** the dispatched body carries the client's items as the client sent them

#### Scenario: Overlap comparison stays bounded and semantic

- **GIVEN** a large legal transcript whose recorded and live items differ only in projection-normalized fields
- **WHEN** the proxy searches for the tail overlap
- **THEN** it compares projected identity fields with a positive recursive enumeration in linear item time
- **AND** it dispatches the client's verbatim items rather than the projected comparison form

#### Scenario: A coincidental content match never costs the client a message

- **GIVEN** a client turn whose first item is byte-identical to an item in the middle of the chain, while being new content
- **WHEN** the join runs
- **THEN** nothing is discarded, because the match is not at the accumulated tail
- **AND** every item the client sent is dispatched

#### Scenario: A chain turn that restated the conversation replaces what it restates

- **GIVEN** a chain whose later turn stored a request repeating earlier turns
- **WHEN** the walk accumulates it
- **THEN** the repeated tail is replaced rather than appended
- **AND** the rebuilt conversation contains no turn twice

#### Scenario: An unlisted wire field does not double the conversation

- **GIVEN** a client restating the chain's turns with any field the wire permits and the recording does not keep — one the implementation has never enumerated
- **WHEN** the join computes the overlap
- **THEN** the restated turns are still recognised, because the key is built from what identifies a turn rather than from what to ignore
- **AND** this holds for a field nested inside a content part or a tool declaration exactly as it holds at the item's top level

#### Scenario: Rewording a tool description does not resend the conversation

- **GIVEN** a client whose tool declarations carry a different description, format or search configuration than the recording kept, while declaring the same tools
- **WHEN** the join computes the overlap
- **THEN** the turns are recognised as restatements and the conversation is dispatched once

#### Scenario: The item count is bounded

- **GIVEN** a chain within the turn and byte bounds whose turns carry very many small items
- **WHEN** the rebuild walks it
- **THEN** it refuses once the item bound is passed, rather than doing unbounded per-item work

#### Scenario: The byte bound is a whole-transcript bound

- **GIVEN** a chain whose turns are individually within the byte bound but whose total exceeds it
- **WHEN** the rebuild walks the chain
- **THEN** it refuses, rather than admitting every turn because each one fits

#### Scenario: A failed turn is not rebuilt as an answered one

- **GIVEN** a turn whose spool ends in a terminal event reporting failure rather than an answer
- **WHEN** the rebuild reaches that turn
- **THEN** it is not treated as settled material
- **AND** the rebuild fails closed rather than presenting the failure as the assistant's answer

#### Scenario: An incomplete spool fails closed

- **GIVEN** a turn in the parent chain whose event spool is marked incomplete, or whose stored request body is missing
- **WHEN** relocation is evaluated
- **THEN** no rebuilt body is produced
- **AND** the request keeps today's owner-unavailable behaviour

#### Scenario: Unsettled tool state fails closed

- **GIVEN** a rebuilt body whose final turn contains a tool call with no matching output
- **WHEN** the strict account-neutral predicate runs
- **THEN** the rebuild is rejected and the request stays owner-bound

#### Scenario: A transport without durable material keeps failing closed

- **GIVEN** an anchored turn on a transport that records no durable operation material for its parent turns
- **WHEN** its owner account answers with a definitive quota rejection
- **THEN** no rebuild is attempted and the request keeps today's owner-unavailable behaviour
- **AND** the outcome is reported as an absent transcript, not as a failed rebuild

#### Scenario: A deterministic non-quota rejection is not relocated

- **GIVEN** the owner answers with an invalid-request rejection
- **WHEN** relocation is evaluated
- **THEN** the rejection is surfaced
- **AND** no other account is attempted, because another account would reject it identically

### Requirement: Ambiguous eventless dispatches relocate once behind the durable fence

An ambiguous eventless transport failure MAY relocate at most once and only through the atomic durable recovery claim. Relocation requires no visible output, no response id, zero spooled events, age within the ambiguity window, a transport-provided side-effect replay-dedupe identity, and a strictly account-neutral rebuilt body. Missing any condition MUST fail closed without inventing another dispatch.

#### Scenario: One ambiguous failure buys one relocation

- **GIVEN** an eventless operation whose transport failed with `stream_incomplete`
- **WHEN** relocation is evaluated and the claim succeeds
- **THEN** the turn is dispatched once on another account
- **AND** a second ambiguous failure for the same operation is refused and terminates through its transport's existing fail-closed outcome without a second dispatch

#### Scenario: A spooled event proves execution and blocks relocation

- **GIVEN** an operation with at least one spooled response event
- **WHEN** the transport fails ambiguously
- **THEN** relocation declines without consuming the claim
- **AND** the request terminates as it does today

#### Scenario: A stale ambiguity is not relocated

- **GIVEN** an eventless ambiguous operation whose dispatch is older than the ambiguity window
- **WHEN** relocation is evaluated
- **THEN** relocation declines
- **AND** the claim is not consumed

#### Scenario: Duplicate side effects are suppressed, not executed

- **GIVEN** a relocated ambiguous dispatch that reproduces a side-effecting tool call the origin dispatch may already have emitted
- **WHEN** the replacement account emits that call
- **THEN** the existing side-effect replay dedupe suppresses it
- **AND** the suppression uses the dedicated terminal failure rather than executing the call twice

### Requirement: A relocation dispatch starts from a fresh spool

Before a relocated dispatch is sent, the proxy MUST clear any partial event spool recorded for that operation, so a transcript rebuilt later cannot concatenate the abandoned attempt's events onto the replacement's. The clear MUST happen in the same atomic step that consumes the replay claim.

#### Scenario: A partial spool cannot leak into the replacement

- **GIVEN** an operation that spooled a partial, non-terminal event stream before its ambiguous failure
- **WHEN** the relocation claim is consumed
- **THEN** the operation's spool is empty before the replacement frame is sent
- **AND** a later transcript rebuild sees only the replacement's events

## MODIFIED Requirements

### Requirement: Durable replay is limited to ambiguous transport outcomes

The proxy MUST consume an `unknown` recovery-journal record for a fresh
account-neutral replay only after an ambiguous transport outcome, represented
by `stream_incomplete`, `stream_idle_timeout`, or
`upstream_request_timeout`, and only before any response event or downstream
output.

An explicit deterministic `response.failed` error MUST settle normally and MUST NOT consume the recovery fence. A deterministic rejection that proves upstream accepted nothing — an upstream quota or usage-limit rejection with no response event and no downstream-visible output — MAY instead relocate through the unfenced lane defined by "Anchored turns relocate on a rebuilt durable transcript", which consumes no replay budget and is rolled back rather than claimed. Every other deterministic rejection, including an invalid-request rejection, MUST NOT be relocated to another account at all.

#### Scenario: Transport ambiguity permits one replay

- **GIVEN** an `unknown` proof-gated journal record exists
- **AND** the upstream closes or times out before any response event
- **WHEN** the bridge handles the ambiguous transport failure
- **THEN** the record is atomically claimed and the request is replayed once
  on a fresh account-neutral upstream session

#### Scenario: Deterministic failure is not replayed

- **GIVEN** an `unknown` proof-gated journal record exists
- **AND** upstream emits an explicit pre-output `response.failed` such as an
  invalid request rejection
- **WHEN** the bridge handles that terminal event
- **THEN** it forwards the terminal failure
- **AND** it leaves the journal available for settlement without replaying on
  another account

#### Scenario: A deterministic quota rejection takes the unfenced lane

- **GIVEN** an anchored turn whose owner answers with a pre-output quota or usage-limit rejection
- **WHEN** the proxy evaluates relocation
- **THEN** the recovery claim is not consumed
- **AND** relocation, if the strict rebuild succeeds, proceeds on the unfenced lane
- **AND** a failure to rebuild leaves the journal available for settlement

### Requirement: Fenced one-shot recovery dispatch

The durable recovery journal MUST persist a one-shot replay budget for every
recovery-safe request. The budget MUST be at most one dispatch per operation for the whole of that operation's retention, across every replica and every reconnect. The budget MUST be consumed atomically when a replay is
claimed for dispatch, together with the spool clear required by "A relocation dispatch starts from a fresh spool", and a caller that proves the replay never reached the
upstream send boundary MUST restore that claim under the same session owner
fence. A replacement session MUST retain or transfer a fenced origin owner
until the claim is rolled back or settled; selecting a replacement or failing
preflight MUST NOT permanently consume an unsent replay.

The claim MUST be refused unless the preconditions in "Ambiguous eventless dispatches relocate once behind the durable fence" hold. A refused claim MUST terminate the request through the fail-closed outcome its transport already produces, without a second dispatch.

#### Scenario: Concurrent reconnects consume one replay

- **WHEN** concurrent reconnects observe the same ambiguous operation
- **THEN** exactly one owner atomically claims the persisted replay budget and
  other reconnects fail closed without dispatching a duplicate

#### Scenario: Pre-dispatch replacement failure restores the budget

- **WHEN** a replay claim is made but replacement admission or preflight fails
  before the exact upstream frame is sent
- **THEN** the claim returns to the available state and the fenced origin
  owner is released only after that rollback succeeds

#### Scenario: Successful replacement settles the origin journal

- **WHEN** a replacement session dispatches the claimed replay and receives a
  terminal response event
- **THEN** settlement uses the retained origin owner fence before releasing it
  and the replay budget cannot be claimed again

#### Scenario: A restored claim is reusable exactly once

- **WHEN** a claim is restored after a pre-dispatch preflight failure
- **THEN** a later ambiguous failure for the same operation may claim it again
- **AND** after that dispatch the budget is exhausted
