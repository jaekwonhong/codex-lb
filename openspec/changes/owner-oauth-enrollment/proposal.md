# Change: Workspace owner one-click OAuth enrollment

## Why
Workspace sections already expose one-click OAuth enrollment for the current member, but the workspace owner identity is displayed without the same auth-management path. The owner is already a managed account with an exact account-pool identity and Ego Lite profile, so requiring a separate manual flow is unnecessary and inconsistent.

## What changes
- Expose a separate OAuth-only `ownerAuth` descriptor per workspace from Companion account-pool authority.
- Keep the owner out of member-switch candidates and out of the member catalog fingerprint.
- Allow the existing durable OAuth enrollment orchestration to target either a current member or the exact workspace owner.
- Resolve owner browser automation through the existing `OwnerAccountId` and existing `CodexLB-account-*` profile; do not create/copy a profile.
- Reuse the same server-owned post-registration Force Probe and dashboard cache-refresh behavior.
- Gate owner enrollment on an explicit Companion capability so mixed-version deployments fail closed.

## Compatibility
`ownerAuth` is nullable and absent on older Companion versions. Existing member catalog entries, member-switch fingerprint, member mutation paths, and persisted enrollment rows remain compatible. No database migration is required.
