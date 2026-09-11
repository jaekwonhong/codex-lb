# Close residual mutation replay paths before canary

The deployed manual controller still contains a reachable repeated invitation
fallback/reissue loop, despite the current one-time-fallback tests and manual-only
contract. An indeterminate delete also enables an automatic retry, and an invitation
already present at the initial execution inspection is checked only after removal.

Restrict the existing membership execution to its authorized attempt, preserve
failure evidence and ownership, and correct current operational recovery guidance.
Do not introduce automation, schema changes, guessed success, or forced release.
