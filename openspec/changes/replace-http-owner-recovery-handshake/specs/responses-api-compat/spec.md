## ADDED Requirements

### Requirement: HTTP delta continuation never depends on implicit client history reconstruction

When a native Codex HTTP/SSE fresh durable reattach arrives without a client-
supplied `previous_response_id`, the proxy injects the durable completed-response
anchor, the required continuity owner is unavailable for a non-short recovery
reason, a healthy alternate account exists, and the incoming request is not a
verified account-neutral full resend, the proxy MUST NOT return
`previous_response_not_found` for the purpose of asking the client to reconstruct
and resend its local history.

The proxy MUST fail before any upstream dispatch with HTTP 409 and error code
`continuity_recovery_required`. The error MUST state that the current HTTP delta
cannot be moved safely, that retrying the same request does not reconstruct the
missing context, and that recovery requires local Codex session history. The
failure MUST be recorded as a local pre-dispatch refusal so native transport-
failure lifecycle handling does not convert it into an empty or truncated stream.

This rule applies only when the previous-response anchor was injected by the
proxy onto a client-unanchored fresh reattach and an otherwise eligible alternate
exists. A verified full resend MUST keep the existing transparent cross-account
replay path. A client-supplied anchor, file/account-scoped request, no-alternate
case, post-dispatch or downstream-visible failure, or any state whose dispatch
status is uncertain MUST retain the existing fail-closed or ordinary failure
contract and MUST NOT be widened by this requirement.

#### Scenario: Quota-blocked fresh reattach carries only a delta

- **GIVEN** a durable HTTP bridge row has a completed response on account A
- **AND** a fresh reattach sends no `previous_response_id` and only a delta that
  does not prove complete account-neutral history
- **AND** the proxy injects account A's durable response as the anchor
- **AND** account A is quota-blocked while eligible account B is available
- **WHEN** owner recovery is evaluated before any upstream submission
- **THEN** the proxy returns HTTP 409 with `continuity_recovery_required`
- **AND** neither account A nor account B receives the request
- **AND** the proxy does not emit `previous_response_not_found` to solicit a
  client-side full-history resend

#### Scenario: Verified full resend still transfers transparently

- **GIVEN** the same unavailable owner and eligible alternate
- **WHEN** the client request contains a verified account-neutral full resend
- **THEN** the existing proof-gated cross-account replay path is used
- **AND** `continuity_recovery_required` is not returned

#### Scenario: Explicit client anchor remains fail-closed

- **GIVEN** the client itself supplied `previous_response_id`
- **WHEN** that required owner is unavailable and no existing safe replay rule applies
- **THEN** the proxy preserves the existing owner-unavailable contract
- **AND** it does not reinterpret the request as local-history recovery eligible
