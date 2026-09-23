## ADDED Requirements

### Requirement: Legacy provenance dispatch preserves complete-pair compatibility
The repository SHALL accept complete legacy 5H/Weekly pairs with identical nonempty opaque provenance, including unversioned JSON objects, subject to existing row identity and immutable-evidence checks. Explicit unsupported or malformed versions and recognizable incomplete versioned provenance SHALL fail closed rather than use the opaque fallback. Legacy provenance SHALL NOT prove five-hour absence or admit an incomplete epoch.

#### Scenario: Opaque JSON object on a complete legacy pair
- **GIVEN** a complete legacy pair with identical unversioned opaque JSON-object provenance and valid existing row identity
- **WHEN** retention is retried or the epoch is recovered
- **THEN** the same original rows SHALL be returned without rewriting provenance
- **AND** the retained five-hour state SHALL be observed

#### Scenario: Incomplete or versioned evidence cannot use legacy fallback
- **GIVEN** a single legacy Weekly row, an unsupported explicit version, or recognizable incomplete versioned provenance
- **WHEN** retention or recovery is attempted
- **THEN** it SHALL be rejected without rewriting evidence or creating effect authority

### Requirement: Retained five-hour uncertainty remains visible with raw values
The operator UI SHALL render the full retained five-hour state. When the state is unknown, the five-hour history block SHALL explicitly display 미확인 even if a raw numeric row exists. Retained raw values MAY remain visible but SHALL be labeled as unverified original evidence rather than validated final usage. The not_provided state SHALL remain distinct and SHALL NOT invent a percentage. Existing original/effective reset separation and reset invalidation notices SHALL remain visible.

#### Scenario: Unknown five-hour evidence retains a numeric row
- **GIVEN** an incomplete legacy 5H-only epoch or an identity-invalid v2 pair whose API history state is unknown
- **WHEN** the actual history component renders the supplied raw five-hour row
- **THEN** the five-hour block SHALL display 미확인 and distinguish retained raw values from validated evidence

#### Scenario: Valid and absent controls retain their meaning
- **GIVEN** a validated complete pair or validated Weekly-only epoch
- **WHEN** history is displayed
- **THEN** observed evidence SHALL retain its normal rendering and not_provided SHALL display 미제공 without a fabricated percentage
