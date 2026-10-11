## ADDED Requirements

### Requirement: Definitive precreated quota rejections permit proven first-turn alternate-account retry

An HTTP Responses stream MAY reselect another OAuth account after a definitive, pre-response usage-limit 429 only if the complete request is independently proven account-neutral. It MUST maintain the existing retry budget, settlement ordering and side-effect safety; failed proof MUST retain the original owner-bound refusal.

#### Scenario: First-turn quota reject with transient client identity
- **GIVEN** a new Responses request without previous_response_id, account-owned conversation/turn-state, file pin, or required owner
- **AND** its full input and tools pass the account-neutral replay verifier after known transient metadata removal
- **WHEN** the selected account returns a definitive usage-limit 429 before response creation and downstream output
- **THEN** the proxy MUST exclude that account from the bounded next selection and resend only the self-contained projected request
- **AND** its old account identity metadata MUST NOT leak into the replacement dispatch

#### Scenario: Any unsound replay remains impossible
- **GIVEN** an explicit previous response, account-owned turn state, file pin, hard owner, unknown metadata, non-self-contained tool chain, accepted response, visible output, generic burst 429, or single-account routing
- **WHEN** a previous account reaches a usage limit
- **THEN** the proxy MUST NOT replay on a different OAuth account without the existing independent full-context continuity proof
- **AND** the original failure and claim/settlement semantics remain authoritative
