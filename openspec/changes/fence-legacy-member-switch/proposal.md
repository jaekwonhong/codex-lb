# Fence legacy member-switch entry points

Keep the reviewed manual path. Remove HTTP access to legacy cleanup, recovery,
catalog editing, account-pool manipulation and browser-backed GET operations.
Permit only explicitly marked stored reads and managed commands. Version-gate
commands so an old tab cannot use unchanged endpoint names to bypass the new path.

Preserve pre-cutover state instead of inferring a migration from missing files or
expired leases. Expose read-only admission diagnostics. Block new membership on
retained legacy ownership, orphan receipts or quarantined auth. This is a code
candidate and an offline cutover contract, not a deployment or data migration.
