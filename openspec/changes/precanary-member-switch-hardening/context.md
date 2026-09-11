# Pre-canary review boundary

Parent: `artifacts/member-switch-release-20260906`.

The review is static plus synthetic/fake-driver qualification. Production account,
membership, invitation, OAuth and browser actions are excluded. Existing operational
containers and Companion remain unchanged until all candidate checks pass.

## Durable rejection

Companion validation that occurs before a session/browser driver call has a known
no-effect outcome. Returning only an HTTP 409 is insufficient after the backend has
already committed its command intent: a lost or differently parsed response leaves
no child evidence for `reconcile`. Such a rejection therefore needs a completed,
typed participant receipt with the exact request fingerprint. This is distinct from
driver or completion-publication uncertainty, which must remain pending.

## Interrupted final release

Membership finalization persists the release marker before releasing the flow owner.
If Companion stops between those operations, the durable marker is evidence that the
original finalize command crossed no external membership boundary and that only the
local ownership release remains. A later explicit operator `reconcile` may finish
that exact release. Stored GETs and reconstruction remain read-only.

## Stale frontend surface

The production Accounts page imports only the server-run client, locator hook and
manual panel. The old direct Companion client/ranking/reconciliation/rotation-policy
modules are reachable only from their own tests and contain retired cleanup,
recovery, session and browser mutation URLs. They are removed rather than retained
as a second executable contract.
