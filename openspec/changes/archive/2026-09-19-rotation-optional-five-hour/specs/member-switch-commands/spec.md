## ADDED Requirements

### Requirement: Optional five-hour evidence is bound to one fetch
The system SHALL classify base 5H availability from one successful identity-bound Usage response as observed, not_provided, or unknown without inferring it from subscription labels. Only an unambiguous Weekly-only response with null or omitted sibling SHALL establish not_provided. Failed fetches, missing rate-limit evidence, malformed or ambiguous windows SHALL NOT establish absence.

#### Scenario: Successful Weekly-only response
- **GIVEN** one fresh successful identity-bound fetch returns one classified Weekly window and no sibling window
- **WHEN** final usage retention is prepared
- **THEN** the system SHALL retain Weekly and explicit same-fetch 5H absence evidence without fabricating a 5H value
- **AND** Weekly validation, reset-first coordination, quotas and effect authorization SHALL remain required

#### Scenario: Missing evidence is unknown
- **GIVEN** a receipt has no 5H window and no explicit valid absence evidence
- **WHEN** final usage retention is prepared
- **THEN** retention SHALL remain blocked

### Requirement: Optional five-hour history preserves epoch integrity
The system SHALL persist versioned absence provenance with a Weekly-only epoch and validate its identity, fetch, observation timestamp, and expected window set on retention and recovery. It SHALL continue to read legacy complete 5H/Weekly pairs and SHALL NOT reinterpret incomplete legacy epochs as valid absence. Retries SHALL preserve immutable evidence and SHALL NOT replay effects.

#### Scenario: Recover committed Weekly-only evidence
- **GIVEN** a valid Weekly-only epoch was committed before controller state publication
- **WHEN** the controller resumes
- **THEN** it SHALL recover that same immutable epoch without rewriting evidence or replaying effects

#### Scenario: Incomplete legacy pair
- **GIVEN** a legacy epoch contains only a Weekly row without versioned absence provenance
- **WHEN** recovery is attempted
- **THEN** recovery SHALL reject the incomplete epoch

### Requirement: Operator distinguishes absent five-hour evidence
Operator API and UI SHALL distinguish not_provided from unknown or missing 5H evidence for the current member and retained history, with no invented usage percentage. Absence evidence SHALL NOT be projected onto a replacement member.

#### Scenario: Display Weekly-only retained history
- **GIVEN** a validated Weekly-only epoch records not_provided
- **WHEN** an operator reads its history
- **THEN** the API SHALL expose not_provided and the UI SHALL display 미제공 without a percentage
