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

Full-suite follow-up: the beta.9 rebase drops the historical local member-control
Alembic branch entirely. The official upstream revision graph is authoritative;
`member_switch_control_records` and `member_switch_command_receipts` are retained
local extension tables outside that graph. The application drift checker ignores
their missing-table `add_table` diffs rather than creating or stamping a local
revision. Release qualification separately verifies the retained tables and data
before member-switch can be enabled. See the owning `lifecycle-integration-closure`
change for that exact boundary.

The existing local overlay adds exactly three T1 settings to the beta.9 upstream
configuration surface: `oauth_import_dir`, `companion_account_pool_url`, and
`runtime_enabled_model_source_ids`. The first two remain optional (`None`) by
default; the runtime-enabled source list defaults to the empty string and is the
per-process rollout fence for Model Sources intentionally disabled in the shared
DB. Their import root, trusted Companion endpoint, and process-local source scope
must remain explicit deployment inputs rather than inferred values. The generated
reference therefore exposes 99 total settings and documents all three local knobs.
No additional setting is introduced by this review.
