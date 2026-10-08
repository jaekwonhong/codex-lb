# Validation — 2026-10-08

## Current pre-retirement state

- WMC task 4.4 remains green and owns production workspace-membership writes.
- OpenCodex 2.80.0 is ready on port 10101 with native OpenAI as the default
  provider and direct `dgx-glm53` routing.
- Mac selects `model_provider = "opencodex"` at the 10101 endpoint.
- PC1 active-session evidence is retained in `evidence/pc1-active-session.json`.
  All nine ProviderSwitcher checks pass; the receipt SHA-256 is
  `22b2e70d14f53f4434a0351ef632e79d138062997928ae74de296186aed627b6`.
- A later PC1 defect qualification found and fixed the missing OpenCodex Desktop
  GLM catalog route. The shared ProviderSwitcher single-ingress branch was
  intentionally frozen after the audited handoff descendants at
  `0a218f5378312758e1af6e0d0778df459a3677a7`; subsequent PC2-pending work is
  isolated on `ops/provider-switcher-opencodex-owner-20261008`, currently
  `dfe84e91`.
- PC1 currently uses `model_provider="opencodex"` with a managed
  `opencodex-merged-*` catalog containing exactly one routed
  `dgx-glm53/glm5.3-flash` row, no bare/legacy GLM row, hard context 1,048,576,
  automatic compact threshold 192,000 and default reasoning `low`.
- PC1 live response canaries through the current OpenCodex config/auth stack are
  green: `gpt-6.1-sol` -> `OPENAI_OK` and
  `dgx-glm53/glm5.3-flash` -> `GLM_OK`; both emitted `turn.completed`, no error
  event and exit 0. Evidence SHA-256 values are
  `df60d7c19464250dfefba5b82260ad739c87955c3ca14a7731c795ca408d6a45`
  and `bcb265ebd3f0f99e089bf639399aca678fcb1e18af5759016094cfff82ce04a9`.
- The retained original PC1 schema-v1 receipt was produced with collector
  SHA-256
  `44f6b66d1e5125fbac32c76482c757b9d2b19619cdff14274721d96e38cbcb3a`.
- At the observation point, ports 2455 and 2456 had no established client
  connection, but both Stable/Beta services and their Tailscale Serve entries
  remained active as rollback-compatible production paths.

## Blocking evidence

### Historical pre-fix handoff — superseded

An earlier PC2 handoff was Taildrop-delivered before the PC1 OpenCodex GLM
catalog defect was found. It contained:

- collector PS1:
  `44f6b66d1e5125fbac32c76482c757b9d2b19619cdff14274721d96e38cbcb3a`;
- finalizer PS1:
  `3c05f989e228cf812410d1bc191bae454f9fe8219afdfb0800dd07f019dde62a`;
- finalizer CMD:
  `8d44ef860482343f553f5d967011daeb6c622c0236d2e1b5ba2312f51cb20294`.

That delivered handoff is **superseded** and SHALL NOT be executed. The later
intermediate replacement bundles are also superseded by the collector-bound
schema-v2 bundle below.

### Current PC2 pending handoff

The current handoff is fully prepared and qualified but **has not been sent to
or executed on PC2**. Therefore the remaining PC2 blocker is no longer package
preparation; it is only the explicitly deferred PC2-local transition and the
resulting fresh schema-v2 PASS receipt.

The currently valid pending handoff is **collector-bound schema version 2**. It
supersedes the originally delivered pre-fix files, schema-v1 staging, and the
intermediate schema-v2 bundle whose manifest/outer hashes were
`712605a9...` / `89a961a4...`. It remains staged only on PC1 and has not been
sent to or executed on PC2:

- qualified product revision:
  `eb8f8e38b06b4aaa819b045dd0498ee4ff9681ea`;
- collector-bound handoff/manifest revision:
  `81a4da70cd2e8883500688e282bd5683db507962`;
- ProviderSwitcher owner branch documentation tip:
  `dfe84e91`;
- product ZIP SHA-256:
  `fe7b0eb665ad880d2bc36c3a9a0df1beb8f9a2094aa051148b4c108566951e37`;
- packaged `Test-ActiveDesktopSession.ps1` SHA-256:
  `36251ead0f645bdad5ea6d92fc7e98e5ca3af2c603486a27b9041829eb1c498a`;
- schema-v2 collector SHA-256:
  `8434759d20ad4527c9a426c85c7c6f6a4af9bcd00d8d95d332ad3062df6d4655`;
- schema-v2 finalizer SHA-256:
  `81469d845023d99a85246bc3a6ef170240c19bcbe7d7b90cc9b53d73968db53a`;
- schema-v2 handoff manifest SHA-256:
  `2b102dff9d7bfdf0e3f781443146dd10ac87ed01d0e8ac4940e31d5509d8ce3a`;
- outer pending handoff ZIP SHA-256:
  `052c184d0a52816d9b31b9872077419c29ca64c66819017496d17d657670501d`.

The exact staged schema-v2 collector bytes were exercised on PC1 without
changing the current config. The collector/finalizer requires the original nine
active-session checks plus real native OpenAI and routed GLM canaries before
emitting a final PASS receipt, and the receipt now includes the collector's own
SHA-256. The PC1 qualification produced schema `2`, result `PASS`:

- PC1 schema-v2 receipt SHA-256:
  `290574ab6f5b70bdd9ddba3e7da941d93759b220435398438ca8cc2cee30886f`;
- `collectorSha256`:
  `8434759d20ad4527c9a426c85c7c6f6a4af9bcd00d8d95d332ad3062df6d4655`;
- `gpt-6.1-sol` / `PC_OPENAI_OK`: PASS, `turn.completed`, zero error events,
  evidence SHA-256
  `bc113eecfdc69a7b7f23d69d2101d0571ca2348cfd295365978e05b1281f15c3`;
- `dgx-glm53/glm5.3-flash` / `PC_GLM_OK`: PASS, `turn.completed`, zero error
  events, evidence SHA-256
  `4322747dcdd3ee12a96f8a217783672c19c6213a76cfc7e87f6b0595d7254503`.

PC2 retirement admission now fail-closes unless the PC2 receipt is schema 2 and
both model canaries pass. A schema-1 PC2 receipt is intentionally invalid even
if all nine older active-session checks pass. The receipt is additionally bound
to the exact qualified PC2 product before it can authorize retirement:

- product version must equal
  `1.4.19+eb8f8e38b06b4aaa819b045dd0498ee4ff9681ea`;
- `collectorSha256` must equal
  `8434759d20ad4527c9a426c85c7c6f6a4af9bcd00d8d95d332ad3062df6d4655`;
- packaged `Test-ActiveDesktopSession.ps1` SHA-256 must equal
  `36251ead0f645bdad5ea6d92fc7e98e5ca3af2c603486a27b9041829eb1c498a`;
- the final Codex config and both model-canary evidence hashes must be valid
  SHA-256 values;
- `observedAt` must be timezone-aware, no more than one hour old, and no more
  than five minutes ahead of the retirement host clock.

This prevents an older ProviderSwitcher build, a stale previously successful
PC2 session or malformed canary evidence from opening the data-plane retirement
gate.

The read-only retirement gate and guarded mutation/rollback runner are isolated
on `ops/opencodex-retirement-owner-20261008`, currently `f2c4960f`. The combined
retirement gate and runner suites pass 29 tests. A live `plan` execution is mutation-free and
currently reports `BLOCKED_PC2_LOCAL_CUTOVER` with exit 3 while confirming Mac
direct ingress, PC1 receipt validity, OpenCodex native OpenAI/GLM prerequisites,
WMC readiness/fences, Stable/Beta running state, zero established 2455/2456
clients, exact preserved container identities/restart policies and the expected
2455/2456 Serve targets. The runner requires the literal confirmation token plus
a valid PC2 receipt before it can stop containers or alter Serve state; partial
apply failures automatically restore the captured container/Serve snapshot.

A temporary **synthetic** schema-v2 PC2 receipt matching the exact pinned
package, collector, verifier, config-hash shape and model-canary contract was
then supplied to the read-only `plan` action solely to test whether any hidden
non-PC2 blocker remained. It returned
`READY_TO_RETIRE_CODEX_LB_DATA_PLANE`, exit 0, and `wouldMutate=false`; the
synthetic file was deleted immediately afterwards and is not valid production
cutover evidence. With the PC2 receipt omitted, the same live plan remains
`BLOCKED_PC2_LOCAL_CUTOVER`. This proves the real fresh PC2 schema-v2 PASS
receipt is the only remaining task-4.5 admission blocker.

The preflight now independently verifies control-plane quiescence instead of
inferring it from idle inference ports. Authenticated WMC `/v1/status` currently
reports schema 1, three workspaces, no active membership operation and zero
enabled workspace rotation intents. Both live Codex-LB containers report no
`member-rotation-runtime/canary-plan.json`. A read-only query against the shared
production PostgreSQL state currently reports all zero for:

- retained unsafe member/auth control records;
- quarantined member-auth accounts;
- pending legacy OAuth flows;
- OAuth device-flow slots.

The retained q2 Controller history remains inert evidence: released terminal
`failed` rows and the released `recovered` row are explicitly accepted as
history and were not replayed. A retained failed handoff whose completed
auth-enrollment parent and child both have released scope/pending state is also
accepted as inert history. Any nonterminal/unknown control kind, pending action,
quarantined auth, pending OAuth flow, device slot, active WMC operation, enabled
rotation intent or live canary plan makes retirement fail closed.

The runner now also requires real inference after the structural retirement
check. It reads the existing Mac command-backed OpenCodex credential only into
memory and calls the Responses surface directly. This exact non-mutating canary
path was live-qualified before retirement: `gpt-6.1-sol` returned
`RETIRE_OPENAI_OK` with response SHA-256
`3ad9cb92ed9a353c73f83e2af3efd8ac2348de87b789fa504bb7efdd776dd790`,
and `dgx-glm53/glm5.3-flash` returned `RETIRE_GLM_OK` with response SHA-256
`849da118ac74bfc8b756361904e5c44686b1812db834db05e6478e37711d0e67`.
If either post-retirement inference canary fails during the eventual apply, the
same captured Stable/Beta/Serve snapshot is automatically restored.

Before the first Docker/Tailscale mutation, the runner now also seals the exact
PC1 and PC2 admission receipts into the retirement evidence directory and
records their SHA-256 values plus the SHA-256 values of the retirement runner
and gate scripts in `before.json`. If either receipt disappears before this
sealing step, `apply` aborts before any mutation. This makes the eventual 4.5
closeout and later rollback evidence self-contained rather than dependent on the
original client receipt paths remaining available.

This missing receipt is a hard task-4.5 retirement blocker. Idle 2455/2456
connections do not replace the missing client proof, and Stable/Beta must not be
stopped or unpublished until PC2 evidence passes.

No workspace membership mutation, q2 replay, account reauthentication, or
credential migration was performed while collecting this evidence.
