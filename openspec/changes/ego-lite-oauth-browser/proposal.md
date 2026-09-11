# Ego Lite OAuth browser

## Why

OAuth-only enrollment currently renders the device verification URL as a normal
browser link. That loses the managed member identity boundary because macOS opens
the user's default browser instead of the browser state assigned to that member.
The installed Ego Lite browser provides profile-scoped task spaces that can reuse
the intended member's login state without disturbing the user's ordinary browser.

## What Changes

- Bind each managed account to a deterministic Ego Lite profile id derived from
  the stable account-pool account id.
- Open device-code verification in an Ego Lite task space owned by that exact
  profile; never fall back to the system browser or the legacy CDP browser.
- Make browser opening a durable OAuth-enrollment command with explicit identity,
  outcome, and recovery state.
- Hand the opened Ego task space to the user for manual login/device-code entry.
- Keep existing CDP paths for workspace observation and member-switch operations;
  this change only replaces the OAuth-only verification browser.

## Impact

No membership mutation, account-token schema migration, or automatic rotation is
introduced. Existing completed OAuth-enrollment records remain historical. Ego
profiles are provisioned separately and must exist before browser open succeeds.
