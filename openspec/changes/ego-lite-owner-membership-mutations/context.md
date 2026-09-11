# Context

Owner membership reads now use deterministic Ego Lite Task Spaces, but the same `IMemberSwitchBrowser` still delegates delete/invite/cancel-invite to `CdpMemberSwitchBrowser`. This leaves a visible transport switch at the first actual membership mutation and means the owner CDP remains an execution dependency.

The migration reuses the existing request expressions and server-side reconciliation semantics. A delete whose response is uncertain is never blindly repeated except for the existing exact 404 identity-missing case; subsequent exact owner Ego reads determine whether removal occurred. Invitation uncertainty is likewise settled by owner Ego observation. Invite cancellation needs an explicit ambiguous-outcome path because the old code treated every non-success other than known 404 as definitive failure.

The deterministic owner Task Space remains agent-controlled during successful reads and mutations. If login is missing or the owner email is wrong, only that exact owner Space may be handed to the user for correction; no legacy CDP or default browser fallback is permitted.

Owner personal-account confirmation is also routed through the deterministic owner Task Space. Recipient personal/workspace and invitation-acceptance paths remain on their existing transport; the adapter selects Ego Lite only when the email is the stable owner account of a managed workspace. Owner cleanup closes only the exact confirmed owner Task Space and preserves the Ego Lite profile login.
