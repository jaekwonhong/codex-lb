# Participant-contract review boundary

Parent candidate: `artifacts/member-switch-contracts-20260906`. This change is an
incremental review candidate and does not deploy or modify its parent.

The expanded C# selection includes browser assistance and session readiness, not
only MemberSwitch classes. New fake-driver regressions exercise the real services
and source-generated response serializer. The emitted JSON is consumed through
the Python HTTP adapter by ASGI tests using production dependency construction,
real temporary SQLite account repositories and durable run/handoff stores.

The transport is intercepted in memory. OAuth is replaced before constructing a
real upstream participant. No operational server, profile, account, HTTP listener
or database is part of qualification. Cross-host HTTP routing and upstream OAuth
remain outside this evidence.

Three boundaries motivated implementation changes: retained target identity on
verification-page failure; exact current operation ownership before browser
assistance; explicit uncertainty after a browser-driver exception. Missing
`outcomeUnknown` response metadata fails closed rather than assuming an old
participant can prove no effect. Backend and Companion must therefore be updated
together after a separate rollout decision. No new database migration is added.

For example, code entry may succeed remotely and then throw while its response is
read. The old implementation deleted its local target record and opened another
tab. The revised contract preserves that record and the parent's pending command.
This prevents replay; it does not assert successful recovery. Universal durable
browser/session receipts, old-client fencing and unattended automation remain
unqualified.
