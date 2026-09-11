## ADDED Requirements

### Requirement: Legacy control-schema adoption preserves migration history

The application migration runner SHALL leave merged migration files unchanged.
When the member-control revision is pending and its tables already exist, it SHALL
execute all missing predecessor revisions normally, validate the frozen control and
receipt schema and receipt references, create only missing counterparts, and record
only that revision in the same transaction. It SHALL NOT infer a complete database
schema from the presence of control tables or skip unrelated migrations.

#### Scenario: A legacy database has compatible retained controls
- **WHEN** the requested upgrade crosses the member-control revision and compatible control tables already exist
- **THEN** the application runner preserves their rows and completes all predecessor migrations before acknowledging that revision
- **AND** subsequent revisions execute normally

#### Scenario: Existing state is incompatible
- **WHEN** a control table has an incompatible column, constraint, default or receipt reference
- **THEN** the compatibility path rejects it before creating a missing counterpart
- **AND** does not acknowledge the control revision

#### Scenario: Fresh database
- **WHEN** neither control table exists
- **THEN** the application runner uses the unchanged original migration

#### Scenario: Upgrade stops before member control
- **WHEN** the target revision precedes member control
- **THEN** this compatibility path does not create, acknowledge or alter member-control state
