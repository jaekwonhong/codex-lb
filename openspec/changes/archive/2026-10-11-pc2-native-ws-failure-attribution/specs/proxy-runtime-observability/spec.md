## ADDED Requirements

### Requirement: Native WebSocket receive diagnostics use allowlisted phases

On a native egress WebSocket receive exception, the adapter MUST carry a diagnostic `native_failure_phase` only when the native failure phase matches a fixed code-defined allowlist. The HTTP bridge `reader_failure` event MUST report that phase, or `None` if unavailable. The diagnostic MUST NOT include raw exception text, upstream addresses, prompts, account credentials, or arbitrary helper-supplied values.

#### Scenario: Native upstream transport error

- **WHEN** the helper reports `transport` or `consumer_backpressure` on a receive failure
- **THEN** the `reader_failure` log includes `native_failure_phase=transport` or `native_failure_phase=consumer_backpressure` respectively
- **AND** the existing `response_events_seen` is preserved

#### Scenario: Untrusted or absent phase

- **WHEN** native failure phase is not in the allowlist or a non-native WebSocket closes
- **THEN** the `reader_failure` log includes `native_failure_phase=None`
- **AND** the untrusted value is not included in this diagnostic

### Requirement: WebSocket failure diagnostics must not change request behavior

Native diagnostic phase attribution MUST NOT alter client-visible error messages, HTTP status, stream settlement, account-health classification, retry eligibility, account selection, or continuity ownership. A request that delivered model output before transport failure MUST NOT acquire new replay permission through the diagnostic field.

#### Scenario: Failure after model output

- **GIVEN** an HTTP bridge request has delivered model output before the upstream WebSocket drops
- **WHEN** the adapter attaches an allowlisted diagnostic phase
- **THEN** the request keeps its existing `stream_incomplete` failure behavior and no-unsafe-replay guarantee
- **AND** the downstream client does not receive the diagnostic phase as a new error detail
