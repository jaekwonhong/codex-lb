# Context

Baseline: operational main e71685b826a5eb3407a4cfc8ffa9a8ffecc3c1a0 and
member-switch-preeffect-closeout-20260908 sealed source.

New-work admission must still reject unknown, orphaned, cross-parent or pending
handoffs. An exact current enrollment's completed child command is not competing
work, even while its OAuth authorization remains pending. Tests must persist that
child rather than substitute an in-memory auth-service fake.

Background token writes retain the repository's ciphertext compare-and-set and
manual preserve-policy behavior. No unconditional write or token-exchange retry
is added.

Resetting an OAuth screen only invalidates local consumers. It does not claim to
cancel a request already accepted by the server. Late responses cannot complete
a different flow or create new timers after the consumer is gone.

Full-suite follow-up: legacy bootstrap deliberately supports pre-created schema
and old revision identifiers. Integration places the member-control compatibility
handling in the application migration runner, not in the already-merged migration.
The original revision bytes and graph are unchanged. See the owning
`lifecycle-integration-closure` change for exact-boundary validation and transaction
requirements. Direct raw Alembic replay of a pre-materialized schema is not adopted
automatically; operators use the application migration command.

The existing local overlay adds exactly two settings to upstream's 131-field
budget: oauth_import_dir and companion_account_pool_url. Both remain optional
(None) by default. Their paths/trust endpoints differ between Docker and native
installations; deriving or hardcoding them would accidentally authorize an import
root or peer. Retain those existing knobs, document them, and account for this
exact two-field extension without adding unused budget. No settings are introduced
by this review.
