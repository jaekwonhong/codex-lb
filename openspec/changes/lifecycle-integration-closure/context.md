# Context

The previous review repaired legacy replay by editing a migration that was already
merged. That approach is rejected at integration: migration bytes and graph remain
immutable. A new later migration cannot prevent failure in its earlier predecessor.
This is therefore an application migration-tool compatibility repair, not a new
schema migration or permission to stamp arbitrary schemas.

The runner already owns the deployment migration lock and legacy revision remapping.
The compatibility branch is limited to the exact pending member-control revision,
and only when one of its tables already exists. All predecessor revisions must run
normally. At the exact parent boundary, both table contracts and retained receipt
references are validated before creating any missing table. Creation and recording
that one revision share a transaction. A later failure can resume at that recorded
boundary; no table is deleted and no live operation is replayed.

Examples: a legacy database with correct control rows keeps those rows; a database
with a missing uniqueness constraint or orphan command receipt is rejected; a fresh
database still executes the unchanged original migration. Historical review files
are never rewritten to claim this alternative was previously validated.
