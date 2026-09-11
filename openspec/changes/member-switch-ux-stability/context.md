# Scope and evidence

Parent operating main: ccf3874ba4ef39f623b8a68b33a7735d1d10de7c.
Parent sealed source: member-switch-validator-r3-20260906.

This pass targets user-visible request ordering and recovery instructions, not a new
state machine or a canary. The backend remains authoritative. Browser AbortController
only stops local waiting; it is not evidence that membership/OAuth did not execute.
An unresolved run/receipt remains retained and must be read, never replayed on mount.

Checks use deferred replies, mocked transport, synthetic browser APIs and static
artifacts. No real membership, invitation/removal, OAuth or credential driver executes.
A service restart is only a deployment action and must preserve state and predecessors.
