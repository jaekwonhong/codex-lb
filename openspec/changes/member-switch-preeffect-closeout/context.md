# Context

The qualifying case is a terminal `personal_switch_not_confirmed` operation whose trace reached
`confirming_owner_personal_before_membership_change`, never entered a mutation stage, has unknown
membership state, and has no invitation-settlement evidence.

The same error code may also occur after an invitation attempt, so the code alone is never sufficient
evidence for release.
