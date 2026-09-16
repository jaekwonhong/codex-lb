## ADDED Requirements

### Requirement: Local control schema remains outside the upstream migration graph

The application migration runner SHALL use the unmodified upstream migration graph
and SHALL NOT add, stamp, merge or replay a local member-control revision. The
`member_switch_control_records` and `member_switch_command_receipts` tables are local
extension state owned outside that graph. Schema-drift validation MAY ignore the
corresponding missing-table `add_table` diffs so an upstream migration does not
invent a second owner for those tables, but release qualification SHALL separately
verify that both retained tables and their data are present before member-switch is
enabled.

#### Scenario: A legacy database has compatible retained controls
- **WHEN** a database with compatible retained local control tables is upgraded through the upstream beta.9 graph
- **THEN** the application runner leaves those tables and rows outside Alembic ownership
- **AND** all upstream revisions execute normally without stamping a local control revision

#### Scenario: Required retained extension state is absent
- **WHEN** either local control table is absent during release qualification
- **THEN** the deployment is blocked from enabling member-switch
- **AND** the migration runner does not create or stamp a replacement local revision

#### Scenario: Fresh database
- **WHEN** neither control table exists
- **THEN** the upstream migration runner completes only the upstream graph
- **AND** this local member-switch capability remains unqualified until its extension schema is provisioned by a separately qualified owner

#### Scenario: Upstream target changes
- **WHEN** the requested upstream target revision changes
- **THEN** local extension-table presence never changes the upstream revision lineage or causes unrelated migrations to be skipped
