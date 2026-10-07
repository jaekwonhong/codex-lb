# Transfer production workspace-membership ownership to WMC

## Why

The standalone Workspace Member Controller has qualified read-only shadow
operation, one-workspace mutation/no-replay recovery, exact OpenCodex account
evidence, and durable reconciliation. Production Codex-LB still exposes the
legacy manual member-switch writer and starts the legacy rotation scheduler,
which means the single-writer ownership contract is not yet enforced at runtime.

There are currently no active/pending membership operations, no enabled
automatic-rotation intents, and no executable rotation plan. This provides a
quiescent ownership-transfer window without performing a membership effect.

## What changes

- Add an explicitly enabled, bearer-authenticated standalone WMC mutation
  surface for the currently qualified production `switch` workflow.
- Use the same durable shared member-switch journal and claim-before-effect /
  no-replay semantics already qualified by the canary.
- Add a production Companion switch effect adapter that uses the ordinary
  `/operations` endpoint, never the canary endpoint, and requires the qualified
  production membership capabilities.
- Require mutation-enabled WMC startup to prove its database principal is
  writable; keep mutation-disabled shadow mode compatible with the existing
  read-only principal.
- Fence Codex-LB's legacy manual switch creation/commands, rotation-intent write,
  and automatic rotation scheduler when
  `CODEX_LB_WORKSPACE_MEMBERSHIP_WRITER=wmc`.
- Leave legacy read/status surfaces available for rollback/inspection and leave
  OAuth enrollment/account-credential migration to task 4.5.

## Safety boundary

- The cutover itself performs no workspace membership mutation.
- The WMC production route remains loopback-only behind the existing bearer
  admin token.
- `add` and `remove` are not newly activated by this cutover; only the already
  qualified switch workflow is admitted by the production HTTP surface.
- Companion remains the membership-effect adapter. It is not a competing
  control-plane writer because WMC owns the durable command/effect claim before
  invoking it.
- OpenCodex remains the sole inference-account routing/quota/credential writer.
