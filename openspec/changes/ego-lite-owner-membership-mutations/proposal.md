# Ego Lite owner membership mutations

## Why
Owner membership observation already uses each workspace owner's deterministic Ego Lite profile and Task Space, but delete/invite/cancel-invite still delegate to the legacy owner CDP browser. The same verified owner browser authority should own both reads and explicit membership mutations.

## What Changes
Run owner delete, invite, and invite-cancel expressions inside the exact `CodexLB-<stable account id>` owner Ego Lite Profile and `codex-lb-owner-<account id>` Task Space. Revalidate owner login identity before each mutation, preserve uncertain side effects as observation-only recovery, and remove legacy owner-CDP fallback from the managed member-switch browser. Advertise a distinct mutation capability and require it before starting or resuming mutation-capable work.

## Impact
Companion owner browser transport, member-switch mutation recovery, capability negotiation, tests, and operational scope documentation. No database migration, automatic membership action, recipient acceptance migration, or personal-workspace migration.
