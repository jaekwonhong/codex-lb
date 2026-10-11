## ADDED Requirements

### Requirement: Cross-account quota recovery uses owner-complete uninterrupted transcripts

Cross-account quota relocation that depends on durable history MUST prove
every turn completed under the exact anchored response's durable session and
OAuth account. A read-only latest-operation check MUST exclude newer uncertain
output before dispatch. Missing or unproven evidence MUST retain hard
ownership and prevent relocation.

#### Scenario: Complete durable history replaces a quota-exhausted owner
- **GIVEN** the shared relocation verdict proves a portable body containing
  rebuilt durable history after a definitive owner 429
- **AND** the entire completed chain belongs to the stored anchor's session
  and OAuth owner, with no later persisted operation
- **WHEN** another account is eligible
- **THEN** the bridge MAY replay the complete history in a new account-neutral
  session without the original previous_response_id

#### Scenario: Missing, mixed or interrupted ownership fails closed
- **GIVEN** the shared relocation verdict proposes rebuilt durable history
- **AND** any chain event is incomplete, from another session/account, does
  not complete the exact response, or the anchor is not the latest
  uninterrupted operation
- **WHEN** the original OAuth owner rejects a new turn due to quota
- **THEN** the bridge MUST NOT cross-account dispatch that history
- **AND** the existing local-history recovery contract and claim/settlement
  guarantees remain in force

#### Scenario: Owner admission races a newer durable operation
- **GIVEN** a fresh upstream socket initially reconstructs the previous
  owner's completed history using the durable transcript
- **AND** the current turn cannot be admitted on the old account because of
  definitive quota exhaustion
- **WHEN** a newer uncertain operation appears before alternate-account
  dispatch, even if the shared verdict calls the already rebuilt body
  `client_input`
- **THEN** the bridge MUST recheck the uninterrupted latest-operation proof
  and MUST NOT replay the stale history on another account

#### Scenario: Full client resend does not require unrelated transcript proof
- **GIVEN** the existing shared verdict independently proves that the client
  supplied an entire safe account-neutral resend without needed durable items
- **WHEN** the old owner definitively rejects a fresh turn due to quota
- **THEN** an unrelated absent transcript MUST NOT cause a new owner-scoped
  full-history dependency
