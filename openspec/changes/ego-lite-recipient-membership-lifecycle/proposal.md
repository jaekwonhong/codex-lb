# Change: Move recipient membership lifecycle to Ego Lite

## Why
The managed member-switch flow still uses recipient CDP profiles for personal-session checks, workspace presence/absence confirmation, and invitation acceptance. This causes legacy CDP browser windows to appear after owner-side operations have already moved to deterministic Ego Lite profiles.

## What changes
Route recipient personal checks, outgoing workspace absence checks, incoming workspace presence/hold checks, invitation acceptance, and recipient operational cleanup through the recipient stable account ID and exact `CodexLB-<accountId>` Ego Lite profile. Use a deterministic `codex-lb-recipient-<accountId>` Task Space, verify exact email and user ID before any effect, and never fall back to recipient CDP in the managed member-switch lifecycle. Preserve the existing user-login browser surfaces outside managed member switching.

Invitation acceptance uses the existing authenticated ChatGPT acceptance endpoint contract after exact recipient identity and invitation binding are proven. Unknown acceptance effects are settled by the existing owner/recipient observations and are never replayed automatically.

## Scope
Companion recipient personal/workspace transport, invitation-acceptance transport, managed-run capability negotiation, UI/help text, tests, and deployment evidence. No owner transport change, OAuth issuance change, database migration, or general login-browser migration.
