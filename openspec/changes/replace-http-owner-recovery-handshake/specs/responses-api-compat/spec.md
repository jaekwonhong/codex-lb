## ADDED Requirements

### Requirement: HTTP delta continuation never depends on implicit client history reconstruction

When a native Codex HTTP/SSE fresh durable reattach arrives without a client-
supplied `previous_response_id`, the proxy injects the durable completed-response
anchor, the required continuity owner is unavailable for a non-short recovery
reason, a healthy alternate account exists, and the incoming request is not a
verified account-neutral full resend, the proxy MUST NOT return
`previous_response_not_found` for the purpose of asking the client to reconstruct
and resend its local history.

The proxy MUST fail before any upstream dispatch with HTTP 400, error type
`invalid_request_error`, and error code `continuity_recovery_required`. A locally
proven JSON refusal MUST carry `x-should-retry: false` and MUST NOT advertise a
contradictory Retry-After header. HTTP 409 MUST NOT be used as a non-retry signal.
The error MUST state that the currently available context does not permit safe
reassignment, that repeating the request cannot reconstruct context, and that
the client can wait for the original owner or recover a new thread from local
Codex history while preserving the existing thread. The
failure MUST be recorded as a local pre-dispatch refusal so native transport-
failure lifecycle handling does not convert it into an empty or truncated stream.

The same terminal recovery contract also applies to a native backend request that
contains a client-supplied `previous_response_id` when its owner cannot be proven
inside the current API-key scope before dispatch. The proxy MUST NOT resolve that
anchor across API-key scopes, guess an owner, or dispatch the anchored delta to a
different account. This owner-proof-loss case is distinct from a known owner that
is merely unavailable: when a known owner remains provable, existing safe replay,
wait, and fail-closed rules continue to apply unless another requirement explicitly
permits recovery.

A verified full resend MUST keep the existing transparent cross-account replay
path. File/account-scoped requests, post-dispatch or downstream-visible failures,
and any state whose dispatch status is uncertain MUST retain the existing
fail-closed or ordinary failure contract and MUST NOT be widened by this
requirement.

Both the native Codex identity and the native backend SSE contract MUST be
present. SDK requests on the backend route and all `/v1/responses` requests MUST
retain their existing owner-unavailable contract. A User-Agent alone MUST NOT
change the contract of a `/v1/responses` request. Originator-based native identity
MUST work without requiring a particular User-Agent spelling.

#### Scenario: Quota-blocked fresh reattach carries only a delta

- **GIVEN** a durable HTTP bridge row has a completed response on account A
- **AND** a fresh reattach sends no `previous_response_id` and only a delta that
  does not prove complete account-neutral history
- **AND** the proxy injects account A's durable response as the anchor
- **AND** account A is quota-blocked while eligible account B is available
- **WHEN** owner recovery is evaluated before any upstream submission
- **THEN** the proxy returns HTTP 400 with `continuity_recovery_required`
- **AND** the JSON response says `x-should-retry: false`
- **AND** neither account A nor account B receives the request
- **AND** the proxy does not emit `previous_response_not_found` to solicit a
  client-side full-history resend

#### Scenario: Verified full resend still transfers transparently

- **GIVEN** the same unavailable owner and eligible alternate
- **WHEN** the client request contains a verified account-neutral full resend
- **THEN** the existing proof-gated cross-account replay path is used
- **AND** `continuity_recovery_required` is not returned

#### Scenario: The owner fails admission after advice was unavailable or stale

- **GIVEN** a native delta depends on a proxy-injected durable response anchor
- **AND** the initial owner advice times out or does not detect pressure
- **WHEN** session creation subsequently rejects that owner before upstream dispatch
- **THEN** the proxy MUST NOT retire the owner or clear the anchor to send the delta on another account
- **AND** a bounded read-only reassessment that confirms a healthy alternate produces the same recovery-required refusal
- **AND** absent alternate evidence preserves the ordinary owner-unavailable failure without retirement or a second dispatch

#### Scenario: Explicit client anchor loses owner proof after API-key scope changes

- **GIVEN** native Codex supplies `previous_response_id` from a prior successful turn
- **AND** the prior response belongs to a different proxy API-key scope
- **AND** current-scope owner lookup therefore returns no owner proof
- **WHEN** the request reaches either HTTP-bridge admission or the raw-HTTP fallback before dispatch
- **THEN** the proxy returns HTTP 400 with `continuity_recovery_required`
- **AND** the response says `x-should-retry: false` and advertises no Retry-After
- **AND** the proxy neither performs a cross-API-key owner lookup nor dispatches the request

#### Scenario: Native Codex carries SDK-compatible transport metadata

- **GIVEN** the same explicit previous-response owner-proof-loss case
- **AND** the backend request is first-party Codex by a recognized native `originator`
- **AND** the request also carries SDK-compatible transport metadata that causes the public response layer to select its SDK-compatible wire contract
- **WHEN** HTTP-bridge admission evaluates whether the anchored continuation can move
- **THEN** the native `originator` remains authoritative for this narrow pre-dispatch recovery decision
- **AND** the proxy returns the same HTTP 400 `continuity_recovery_required` refusal
- **AND** a request that merely looks Codex-like by User-Agent but lacks a recognized native originator does not gain this exception

#### Scenario: Explicit client anchor still has a known owner

- **GIVEN** the client itself supplied `previous_response_id`
- **AND** the proxy can still prove the required owner inside the current API-key scope
- **WHEN** that known owner is unavailable and no existing safe replay rule applies
- **THEN** the existing owner-unavailable or proof-gated recovery behavior is preserved
- **AND** owner proof is not discarded merely to obtain a local-history recovery response

#### Scenario: SDK owner failure does not become a native recovery command

- **GIVEN** the same durable delta, unavailable owner, and eligible alternate
- **WHEN** an SDK uses the backend route, or any client uses `/v1/responses`
- **THEN** the existing owner-unavailable response is preserved
- **AND** the native local-history recovery code is not substituted

#### Scenario: A local refusal after response headers is still terminal

- **GIVEN** response headers have already been committed before local admission finishes
- **WHEN** the native local-history refusal is raised before upstream dispatch
- **THEN** the native stream contains one terminal `response.failed`
- **AND** because native Codex treats unknown failed-event codes as retryable,
  the committed event uses the established non-retry request-error wire code
  `invalid_prompt` while preserving the continuity-recovery message and
  `availability_reason="continuity_recovery_required"`
- **AND** its lifecycle is not converted into an empty transport termination
- **AND** it does not solicit a full-history resend by emitting `previous_response_not_found`
