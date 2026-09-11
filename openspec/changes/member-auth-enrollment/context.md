# Context

This workflow reuses the existing durable auth-handoff and OAuth device-code implementation,
but with an explicit `preserve_other_auth` contract and a distinct durable parent record.
It does not call Companion membership mutation or participant/browser mutation APIs.

The workflow also fences the shared single-active device-code slot. Ordinary dashboard OAuth
acquires the same durable global start scope as managed member work before making its external
OAuth start request. The unique shared scope makes the ordinary-start/managed-start race atomic
across the stable and beta lanes. After ordinary device OAuth returns, the durable device slot
continues to block managed issuance until that older flow completes or expires.

OAuth-only enrollment does not auto-reissue an expired device code. A new enrollment is required
after the failed record is explicitly finalized, which forces fresh membership, catalog, and auth
identity validation before another external device-code request.

`active_auth_count` is operational information, not an identity-collision signal. Multiple active
OAuth identities are valid when every one maps exactly to a different managed member. Unknown,
partial, or duplicate mappings remain fail-closed ambiguity.

Validation uses synthetic membership/OAuth responses only. No live OAuth enrollment,
membership replacement, invitation, account deletion, or automatic rotation is performed.
