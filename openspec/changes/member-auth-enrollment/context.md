# Context

This workflow reuses the existing durable auth-handoff and OAuth device-code implementation,
but with an explicit `preserve_other_auth` contract and a distinct durable parent record.
It does not call Companion membership mutation or participant/browser mutation APIs.

The workflow uses the official shared single-active device-code slot as cross-lane authority.
Managed issuance refuses a slot that is already owned and rechecks the exact managed flow before
advancing OAuth state. An ordinary OAuth start on another lane may supersede the slot under the
official latest-start-wins contract; a superseded managed flow fails closed before auth is applied.

OAuth-only enrollment does not auto-reissue an expired device code. A new enrollment is required
after the failed record is explicitly finalized, which forces fresh membership, catalog, and auth
identity validation before another external device-code request.

`active_auth_count` is operational information, not an identity-collision signal. Multiple active
OAuth identities are valid when every one maps exactly to a different managed member. Unknown,
partial, or duplicate mappings remain fail-closed ambiguity.

Validation uses synthetic membership/OAuth responses only. No live OAuth enrollment,
membership replacement, invitation, account deletion, or automatic rotation is performed.
