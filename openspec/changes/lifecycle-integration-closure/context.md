# Context

The previous review introduced a local member-control migration branch. That branch
is intentionally dropped by the beta.9 rebase: the upstream migration bytes and
graph remain authoritative, and the retained member-control tables are local
extension state outside Alembic ownership.

The runner still owns the deployment migration lock and all upstream migration
execution. Its local compatibility rule is deliberately narrower: schema-drift
checking ignores missing-table diffs for `member_switch_control_records` and
`member_switch_command_receipts` so the upstream runner never invents or stamps a
second owner for those tables. Release qualification separately verifies that both
tables and retained data are present before member-switch is enabled. All upstream
revisions run normally and no live operation is replayed.

Examples: the production-lineage database keeps its retained local control rows
while beta.9 migrations execute; a database missing either extension table is a
member-switch deployment blocker; and a fresh upstream database completes the
upstream graph without silently provisioning this local capability.
