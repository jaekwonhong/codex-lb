## ADDED Requirements

### Requirement: Definitive pre-membership failures can be explicitly closed

The manual member-switch workflow SHALL allow an operator to finalize a terminal failed operation
only when durable Companion evidence proves that no membership mutation was attempted.

#### Scenario: Owner personal-workspace confirmation fails before mutation
- **WHEN** the operation is terminal with `personal_switch_not_confirmed`
- **AND** the trace contains owner-personal confirmation but no membership mutation stage
- **AND** there is no invitation-settlement evidence
- **THEN** the UI offers explicit finish
- **AND** finish releases the retained operation without replaying membership mutation

#### Scenario: Failure contains mutation evidence
- **WHEN** a failed operation has an invitation settlement or a mutation-stage trace entry
- **THEN** explicit finish is not offered
- **AND** the retained operation remains fail-closed for operator review
