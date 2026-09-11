# Account and API-key confirmation integrity

The current account delete/usage-reset and API-key delete dialogs dismiss before
the mutation settles, omit the exact target, and do not consistently honor changed
write access or missing targets. Review and repair these user-visible boundaries.
Use the existing mutation state and confirmation component. No new backend API,
automatic retry, credential operation, member-switch change or schema migration.
