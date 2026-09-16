## ADDED Requirements

### Requirement: Upstream migration remains independent of local member-control extensions

The application migration command SHALL execute the unmodified upstream revision
graph without creating, stamping or remapping a local member-control revision.
Existing `member_switch_control_records` and `member_switch_command_receipts` tables
and their data SHALL remain outside that graph. Release qualification SHALL verify
their presence before enabling member-switch; absence SHALL NOT cause the upstream
migration runner to fabricate replacement extension state.

#### Scenario: Existing control schema survives upstream migration
- **WHEN** both local extension tables exist before the beta.9 upgrade
- **THEN** the application migration runner preserves their rows while executing upstream revisions normally
- **AND** no local member-control Alembic revision is added or stamped

#### Scenario: Local extension schema is absent
- **WHEN** either required local extension table is absent during release qualification
- **THEN** member-switch enablement is blocked
- **AND** the upstream migration runner does not create or acknowledge a local replacement revision
