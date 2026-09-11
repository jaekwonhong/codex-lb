## ADDED Requirements

### Requirement: Legacy migration replay preserves compatible member-control tables

The application migration command's legacy history bootstrap or revision remapping
SHALL retain already-compatible member-control and receipt tables and their
data. It SHALL reject incompatible existing definitions before creating any
missing counterpart. Uniqueness, revision checks and receipt identity constraints
SHALL NOT be silently weakened to complete bootstrap.

#### Scenario: Existing control schema is replayed
- **WHEN** both tables already have the migration's column and constraint contract
- **THEN** the application migration runner preserves their rows and succeeds without recreation

#### Scenario: Existing admission uniqueness is missing
- **WHEN** an existing control table lacks the unique active scope constraint
- **THEN** replay fails before creating or changing either table
