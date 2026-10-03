## ADDED Requirements

### Requirement: Local-history continuity recovery failures are attributable

A locally proven pre-submit HTTP continuity failure with error code
`continuity_recovery_required` MUST use the preflight request-log writer exactly
once. When the log store acknowledges within the one-second persistence budget,
one `request_logs` row MUST be written before the error reaches the client.
A log-store failure or acknowledgement timeout MUST NOT replace the refusal or
skip reservation cleanup; the existing persistence-warning path remains active.
An insert still pending after the budget or caller cancellation MUST remain
tracked by the existing persistence-task lifecycle rather than being submitted again.
The row MUST carry `status="error"`, `account_id=NULL`, the request model, the
conversation id when available, and the same ingress request id used by the
proxy error log. It MUST NOT claim either the unavailable owner or the unused
alternate as the account that executed the request.

The matching code alone is not pre-dispatch evidence. An upstream-originated
exception with the same code MUST NOT create an extra NULL-account preflight row.

The bridge MUST also emit one structured
`owner_pressure_local_history_recovery_required` event containing the normalized
owner-pressure reason, hashed bridge identity, affinity kind, model and failed
owner account id. The event MUST NOT expose the raw previous-response id or raw
conversation content.

For an explicit `previous_response_id` whose owner proof is missing in the current
API-key scope, the bridge or raw-HTTP path MUST record the existing hashed
`continuity_fail_closed` diagnostic with reason
`owner_lookup_miss_local_history_recovery_required`. It MUST NOT log the raw
response id. This diagnostic supplements, rather than duplicates, the single
NULL-account preflight request-log row.

#### Scenario: Fresh reattach cannot move safely

- **GIVEN** a fresh durable HTTP delta is blocked on its unavailable owner
- **AND** an alternate exists but the delta is not portable
- **WHEN** the proxy returns `continuity_recovery_required`
- **THEN** one request-log row records that code with no execution account
- **AND** one structured recovery-required bridge event records why the proxy
  refused automatic migration
- **AND** no success or upstream-error row is fabricated for an account that did
  not receive the request

#### Scenario: An upstream error happens to reuse the local recovery code

- **GIVEN** a provider failure carries the same public code without local
  pre-dispatch provenance
- **WHEN** it propagates through the bridge error wrapper
- **THEN** the wrapper does not record an additional NULL-account preflight error
- **AND** the normal execution-account finalizer remains authoritative

#### Scenario: Native identity is carried only by originator

- **GIVEN** a locally proven recovery refusal for a native Codex originator
- **AND** a thread-id is present without a Codex-prefixed User-Agent
- **WHEN** the preflight row is written
- **THEN** its conversation_id MUST retain that thread-id
- **AND** unrelated SDK/provider log attribution MUST remain unchanged

#### Scenario: Explicit anchor owner proof is missing

- **GIVEN** native Codex supplies an explicit previous-response anchor
- **AND** current API-key-scoped owner lookup returns no owner proof
- **WHEN** the proxy refuses the request before dispatch
- **THEN** exactly one request-log row records `continuity_recovery_required` with `account_id=NULL`
- **AND** the conversation id comes from native thread identity when available
- **AND** a hashed continuity-fail-closed diagnostic records the owner-lookup-miss recovery reason
- **AND** no raw previous-response id or conversation content is logged
