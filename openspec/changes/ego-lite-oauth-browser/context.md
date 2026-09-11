# Context

The host has Ego Lite 0.4.7.4 and `ego-browser` installed. The installed native
runtime exposes `listProfiles()` and `createTaskSpace(name, profileId?)`; task-space
metadata includes the selected `profileId` and ownership. This change treats those
observed APIs as the host integration contract and invokes the pinned local
`~/.local/bin/ego-browser` executable from Companion without a shell.

The account pool already has stable account ids (`account-<32 hex>`). The Ego
profile id is derived as `CodexLB-<account id>`. This avoids adding another mutable
identity mapping and remains stable when display name or observed user id changes.
The Companion resolves the requested preset back to the account pool and verifies
email, user id, workspace id/account id, and catalog fingerprint before opening a
task space.

The OAuth device code remains visible in the dashboard and is entered manually by
the user. Companion does not copy or type the code and does not automate OpenAI
credentials. The Ego task space is handed to the user after navigation. A missing
Ego executable/profile, a task-space/profile mismatch, or ambiguous runtime result
is a visible failure and never triggers a fallback browser.

The installed Ego Lite build reports a successfully handed-off task space as
`ownership=agentDelegatedToUser`. Device-code issuance first verifies the exact
profile through the same trusted Companion/Ego runtime boundary; if the profile is
missing or the runtime outcome is unavailable, OAuth is not started and no device-
code validity window is consumed.

This is intentionally narrower than replacing the current CDP architecture. CDP
continues to serve workspace membership/owner observation and existing member-
switch browser operations until those responsibilities are reviewed separately.
