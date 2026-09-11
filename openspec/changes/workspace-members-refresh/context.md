# Context

`catalog.members` is an allowlisted switch-candidate set, not proof of current upstream workspace membership. The UI therefore needs a separate observation field. The existing catalog GET remains a pure configuration read because backend identity validation depends on it and must not unexpectedly launch or navigate an owner browser.

The new refresh is an explicit operator action. Reconciliation is deliberately narrow: only an existing, included managed account matched by normalized email can have its stored user id corrected. Unknown members are displayed but not adopted. Account readiness, assignments, workspace ownership and automation settings are unchanged.
