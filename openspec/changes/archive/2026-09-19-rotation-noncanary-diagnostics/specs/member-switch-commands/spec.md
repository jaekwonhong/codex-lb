## ADDED Requirements

### Requirement: Non-canary diagnostics have no activation authority
A non-canary diagnostic runner SHALL exclude reset redemption, member removal,
invitation, operation start, enabled intent, plan publication and quota reservation.
It SHALL compare sanitized numeric upstream usage fields with production parsing
and classification without persisting usage. It SHALL use read-only database
transactions and allow only Companion catalog, admission, membership observation
and preview endpoints. Independent checks SHALL report PASS, FAIL, ERROR or
SKIPPED separately; an absent prerequisite SHALL NOT be converted into success.
The resulting report SHALL always declare that it grants no activation authority.

#### Scenario: Final retention lacks 5H input
- **WHEN** a fresh actual usage response cannot produce final retention inputs
- **THEN** the report retains the failure while independently observable later
  checks may still run without an effect or any activation authorization

#### Scenario: Diagnostic attempts an effect endpoint
- **WHEN** the runner attempts a Companion operation or participant command
- **THEN** its allowlist rejects the request before transport
