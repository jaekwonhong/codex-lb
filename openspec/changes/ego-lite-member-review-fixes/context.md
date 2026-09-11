# Scope and recovery authority

The repaired user-facing recipient path uses Ego Lite. Membership observation uses owner CDP; personal-workspace checks and recipient acceptance also still use recipient CDP. These paths are not migrated by this patch.

Unknown effects retain durable intent. GET receipts remain stored reads. Explicit POST reconciliation may publish a closed receipt only after reading the exact persisted Ego target; it MUST NOT close, open, navigate, claim or take over a browser. Legacy receipts lacking sufficient target identity stay blocked for operator review.

After a confirmed close, an existing OAuth handoff is retained and a user may explicitly prepare its exact member session again. That action does not prepare another OAuth handoff, issue a device code, or repeat membership changes. For example, closing an unfinished auth page, preparing the same login, and reopening uses the original handoff.

A completed session query that reports a server/transport/data error is a known not-ready observation: it does not claim logout, issue OAuth, or leave an outstanding browser command. Process timeouts and unconfirmed ownership/side effects still retain OutcomeUnknown and pending intent (F-01).

A closed or failed browser flow remains a recheck gate in the existing `browser_flow_id` field. The field is cleared only by a successful exact-member session check, so UI/server action authority cannot offer direct reopen while the profile still needs verification.

Known session-recheck failure, known browser-open failure, and nonterminal browser close use `needs_attention` as the recovery gate. Nonterminal OAuth observations preserve this gate; only a successful exact-member session recheck returns the run to `auth_prepared` and permits browser reopen.
