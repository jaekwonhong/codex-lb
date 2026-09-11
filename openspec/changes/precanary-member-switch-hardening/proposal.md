# Pre-canary manual member-switch hardening

The deployed manual flow is already fenced from automatic rotation, but static
review found two durable recovery seams that can strand an operator after a
definitive no-effect participant rejection or an interrupted final release.

This change keeps the manual state machine and external-effect policy intact. It
adds durable evidence for deterministic participant rejection, makes an explicit
`reconcile` able to finish a previously persisted release intent, and removes the
unused legacy frontend client modules that still describe retired direct-mutation
routes.

No automatic retry, automatic recovery, membership action, OAuth action or schema
migration is introduced.
