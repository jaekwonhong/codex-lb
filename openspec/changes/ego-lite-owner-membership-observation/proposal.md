# Ego Lite owner membership observation

## Why
The manual member-management panel's explicit catalog refresh still opens legacy owner CDP browsers even though every workspace owner already has a deterministic managed Ego Lite profile. The first read-only action should use the same per-account browser authority as the migrated member/OAuth paths.

## What Changes
Route workspace membership observation through the workspace owner's stable account ID and `CodexLB-<accountId>` Ego Lite profile/Task Space. Verify the exact owner email before reading members/invites, create or reclaim only the deterministic owner Task Space, and fail closed without any CDP fallback. Keep delete/invite/cancel mutations on the existing owner-CDP implementation in this change.

## Impact
Companion membership observation transport, capability negotiation, catalog-refresh backend guard, regression tests, and the member-management help text. No membership mutation, OAuth issuance, database migration, or recipient acceptance/personal-workspace transport change.
