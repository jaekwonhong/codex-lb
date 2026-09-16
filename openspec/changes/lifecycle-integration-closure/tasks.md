- [x] Drop the historical local member-control Alembic branch from the beta.9 rebase.
- [x] Keep the two retained member-control tables outside upstream Alembic ownership and schema-drift creation.
- [x] Require migration rehearsal to verify retained extension tables/data before member-switch enablement.
- [x] Recheck lifecycle regressions and the broad-suite fixture boundary.
- [x] Record integrated evidence and exact candidate identities separately from deployment.

Qualification remains WARN for unavailable independent review, untested live/platform boundaries,
and the historically observed fixture lock whose root cause was not established.
