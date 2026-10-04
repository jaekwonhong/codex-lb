## ADDED Requirements

### Requirement: HTTP delta continuation never depends on implicit client history reconstruction

When a native Codex HTTP/SSE fresh durable reattach arrives without a client-
supplied `previous_response_id`, the proxy injects the durable completed-response
anchor, the required continuity owner is unavailable for a non-short recovery
reason, and the incoming request is not a verified account-neutral full resend,
the proxy MUST NOT return
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

#### Scenario: Owner quota terminal arrives after a verified full resend was folded behind its anchor

- **GIVEN** native Codex supplied a verified account-neutral full resend whose
  stored durable prefix fingerprint matches the current owner
- **AND** the proxy folded that full resend behind the owner's
  `previous_response_id` before dispatch
- **AND** a durable operation fence proves the request identity
- **WHEN** the owner returns `previous_response_owner_unavailable` because of
  quota or usage exhaustion before `response.created`, before any downstream
  output, and before a server-owned replay has occurred
- **THEN** the proxy resets the fenced operation spool and replays the preserved
  verified full resend without the owner anchor on an account-neutral session
- **AND** the failed owner is excluded from replacement selection
- **AND** the operation identity is preserved across the one bounded replay
- **AND** a successful eligible alternate may complete the same client turn
  without `continuity_recovery_required`
- **AND** a delta-only, file/account-bound, downstream-visible, replayed, or
  otherwise unverified request keeps the existing fail-closed recovery contract

#### Scenario: The owner fails admission after advice was unavailable or stale

- **GIVEN** a native delta depends on a proxy-injected durable response anchor
- **AND** the initial owner advice times out or does not detect pressure
- **WHEN** session creation subsequently rejects that owner before upstream dispatch
- **THEN** the proxy MUST NOT retire the owner or clear the anchor to send the delta on another account
- **AND** a bounded read-only reassessment that confirms owner unavailability produces the same recovery-required refusal whether or not a healthy alternate is currently selectable
- **AND** absent alternate evidence MUST NOT downgrade that native delta to the ordinary retry-looking owner-unavailable failure
- **AND** the proxy neither retires the owner nor dispatches the delta to a second account

#### Scenario: Quota-blocked fresh reattach has no currently selectable alternate

- **GIVEN** a native durable HTTP delta depends on a proxy-injected response anchor
- **AND** its proven owner cannot recover inside the bounded short-hold window
- **AND** no healthy alternate is currently selectable
- **WHEN** owner recovery is evaluated before upstream submission
- **THEN** the proxy returns HTTP 400 with `continuity_recovery_required`
- **AND** the response remains locally non-retryable rather than returning `previous_response_owner_unavailable`
- **AND** no account receives the delta

#### Scenario: Explicit client anchor loses owner proof after API-key scope changes

- **GIVEN** native Codex supplies `previous_response_id` from a prior successful turn
- **AND** the prior response belongs to a different proxy API-key scope
- **AND** current-scope owner lookup therefore returns no owner proof
- **WHEN** the request reaches either HTTP-bridge admission or the raw-HTTP fallback before dispatch
- **THEN** the proxy returns HTTP 400 with `continuity_recovery_required`
- **AND** the response says `x-should-retry: false` and advertises no Retry-After
- **AND** the proxy neither performs a cross-API-key owner lookup nor dispatches the request

#### Scenario: Durable session anchor survives but its owner proof is absent in the new API-key scope

- **GIVEN** native Codex sends a delta without naming `previous_response_id`
- **AND** current-scope durable session continuity still supplies a stored response anchor
- **AND** that durable lookup has no account owner proof in the current API-key scope
- **AND** the request is not a verified complete account-neutral resend
- **WHEN** HTTP-bridge admission detects the required continuity owner is missing before dispatch
- **THEN** the proxy returns HTTP 400 `continuity_recovery_required`
- **AND** it preserves API-key isolation rather than searching another scope for the old owner
- **AND** it does not create an upstream bridge session or dispatch the delta
- **AND** a proved complete account-neutral resend keeps its existing safe replay path

#### Scenario: Native Codex carries SDK-compatible transport metadata

- **GIVEN** the same explicit previous-response owner-proof-loss case
- **AND** the request is on the backend Codex session-affinity route
- **AND** first-party Codex identity is proven either by a recognized native
  `originator`, or by a native Codex User-Agent together with a stable backend
  conversation/session identity (`thread-id`, `x-codex-conversation-id`, or
  `x-codex-session-id`)
- **AND** the request also carries SDK-compatible transport metadata that causes the public response layer to select its SDK-compatible wire contract
- **WHEN** HTTP-bridge admission evaluates whether the anchored continuation can move
- **THEN** that strong native backend identity remains authoritative for this narrow pre-dispatch recovery decision
- **AND** the proxy returns the same HTTP 400 `continuity_recovery_required` refusal
- **AND** a User-Agent-only lookalike, turn-state-only request, ordinary SDK, or
  request outside Codex session-affinity does not gain this exception

#### Scenario: Native explicit client anchor has a known but unavailable owner

- **GIVEN** the client itself supplied `previous_response_id`
- **AND** the proxy can still prove the required owner inside the current API-key scope
- **AND** the request is a native backend Codex delta rather than a verified complete account-neutral resend
- **AND** no file/account-scoped constraint requires a separate owner
- **WHEN** that known owner remains unavailable after the bounded short-hold recovery window
- **THEN** the proxy preserves the explicit anchor and owner proof but returns HTTP 400 `continuity_recovery_required`
- **AND** the proxy does not advertise an open-ended retry loop or dispatch the delta to another account
- **AND** a verified full resend keeps the existing proof-gated replay behavior
- **AND** non-native, file-bound, post-dispatch, or ambiguous-dispatch cases retain their existing fail-closed contract

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

### Requirement: A proven revoked access token is not reused for HTTP-bridge admission

When HTTP-bridge session creation receives an upstream authentication failure
whose structured error code is `token_revoked`, the proxy MUST treat that error
as proof that the currently stored access token cannot serve the request. The
proxy MUST perform at most one forced credential refresh for that selected
account before deciding whether the same account is still usable.

If forced refresh yields a usable credential and reconnect succeeds, the request
MAY continue on the same account and the account MUST NOT be downgraded merely
because the previous access token was revoked. If forced refresh fails
permanently, or reconnect with the refreshed credential again returns
`token_revoked`, the account MUST be persisted as `REAUTH_REQUIRED` with a
revoked-access-token reason that makes that account ineligible for ordinary
routing until reauthentication repairs it. A refresh-token-only
`REAUTH_REQUIRED` account whose current access token remains usable MUST retain
the existing request-routable behavior.

For a request that is not hard-bound to the failed account, the failed account
MUST be excluded from the current selection loop and sticky affinity MUST be
reallocated before choosing an alternate. For a hard continuity/file owner, the
proxy MUST preserve the owner constraint and surface the authentication failure
instead of silently crossing accounts.

#### Scenario: Revoked prompt-cache owner transparently fails over before dispatch

- **GIVEN** an HTTP-bridge prompt-cache request selects account A
- **AND** opening A's upstream WebSocket returns structured `token_revoked`
- **AND** one forced refresh does not restore a usable connection
- **AND** healthy account B is eligible and the request is not hard-bound to A
- **WHEN** bridge admission retries selection before upstream request dispatch
- **THEN** account A is persisted as reauthentication-required with revoked-access-token evidence
- **AND** A is excluded from the request-local selection set
- **AND** sticky selection is explicitly reallocated away from A
- **AND** account B may serve the request without exposing the repeated `token_revoked` loop

#### Scenario: Warning-only reauthentication state remains request-routable

- **GIVEN** an account is `REAUTH_REQUIRED` only because its refresh credential needs repair
- **AND** its current access token has not expired and has not been proven revoked
- **WHEN** ordinary selection evaluates that account
- **THEN** the account retains the existing request-routable behavior
- **AND** this change does not globally convert `REAUTH_REQUIRED` into a hard routing exclusion

#### Scenario: Hard owner is not crossed after token revocation

- **GIVEN** a bridge request is hard-bound to account A by continuity or file ownership
- **AND** A returns `token_revoked` and the forced refresh/reconnect path cannot restore it
- **WHEN** bridge admission handles the permanent authentication failure
- **THEN** A is marked with the revoked-access-token reauthentication state
- **AND** the proxy does not select account B for that request
- **AND** the original authentication/owner-unavailable contract is surfaced without cross-account dispatch
