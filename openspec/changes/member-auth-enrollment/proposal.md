# Current-member OAuth enrollment

## Why

The manual member-switch surface can observe the actual current workspace member, but a
member who is already in the workspace has no workspace-scoped route to register missing
device-code OAuth without first attempting a membership replacement.

## What Changes

- Show local OAuth status next to each observed current managed member.
- Add a durable OAuth-only workflow that shares the member-switch global control scope.
- Reconfirm actual membership and exact managed identity before device-code issuance.
- Preserve every other member's auth; do not remove, invite, replace, quarantine, or delete
  membership/auth as part of this workflow.
- Require explicit device-code issuance, auth observation/application, and final release.
- Keep ambiguous, unmanaged, already-active, or quarantined identities fail-closed.
- Serialize ordinary dashboard OAuth start and managed member operations with one shared durable
  start scope before any external OAuth device-code request.
- Treat multiple exact managed OAuth identities in one workspace as distinct valid identities;
  only unknown, partial, or duplicate identity collisions are ambiguous.
- Do not automatically reissue an expired OAuth-only device code. The operator must close the
  failed enrollment and start a new one so current membership and catalog identity are revalidated.
