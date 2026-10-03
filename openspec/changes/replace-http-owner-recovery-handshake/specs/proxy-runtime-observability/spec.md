## ADDED Requirements

### Requirement: Local-history continuity recovery failures are attributable

A pre-submit HTTP bridge failure with error code `continuity_recovery_required`
MUST write exactly one `request_logs` row before the error reaches the client.
The row MUST carry `status="error"`, `account_id=NULL`, the request model, the
conversation id when available, and the same ingress request id used by the
proxy error log. It MUST NOT claim either the unavailable owner or the unused
alternate as the account that executed the request.

The bridge MUST also emit one structured
`owner_pressure_local_history_recovery_required` event containing the normalized
owner-pressure reason, hashed bridge identity, affinity kind, model and failed
owner account id. The event MUST NOT expose the raw previous-response id or raw
conversation content.

#### Scenario: Fresh reattach cannot move safely

- **GIVEN** a fresh durable HTTP delta is blocked on its unavailable owner
- **AND** an alternate exists but the delta is not portable
- **WHEN** the proxy returns `continuity_recovery_required`
- **THEN** one request-log row records that code with no execution account
- **AND** one structured recovery-required bridge event records why the proxy
  refused automatic migration
- **AND** no success or upstream-error row is fabricated for an account that did
  not receive the request
