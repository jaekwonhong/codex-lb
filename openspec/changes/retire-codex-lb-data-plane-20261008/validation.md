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
  `0aa29e4f`.
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
- The receipt collector SHA-256 is
  `44f6b66d1e5125fbac32c76482c757b9d2b19619cdff14274721d96e38cbcb3a`.
- At the observation point, ports 2455 and 2456 had no established client
  connection, but both Stable/Beta services and their Tailscale Serve entries
  remained active as rollback-compatible production paths.

## Blocking evidence

PC2 has received the qualified ProviderSwitcher package, OpenCodex encrypted
bundle, rollout runner, and the exact active-session evidence collector. PC2 is
not yet considered migrated because its local user has not produced a final
`result=PASS` active-session receipt after selecting and confirming
`OpenCodex · 10101`.

The final local handoff was additionally reduced to one interactive finalizer
and Taildrop-delivered to `jaekwonhong` with the exact checksum manifest:

- collector PS1:
  `44f6b66d1e5125fbac32c76482c757b9d2b19619cdff14274721d96e38cbcb3a`;
- finalizer PS1:
  `3c05f989e228cf812410d1bc191bae454f9fe8219afdfb0800dd07f019dde62a`;
- finalizer CMD:
  `8d44ef860482343f553f5d967011daeb6c622c0236d2e1b5ba2312f51cb20294`.

That PC2 handoff was produced before the PC1 OpenCodex GLM catalog defect was
fixed. It is therefore **superseded as a final cutover artifact** and SHALL NOT
be executed while PC2 remains Pending. The collector/finalizer logic may be
reused only after the PC2 rollout package is rebuilt/requalified from the
canonical ProviderSwitcher branch at or after `94fae09f`.

The replacement handoff has now been prepared but **not sent to or executed on
PC2**. It separates the already qualified product revision from the later
handoff-control revision:

- product source: `eb8f8e38b06b4aaa819b045dd0498ee4ff9681ea`;
- canonical handoff source tip:
  `0a218f5378312758e1af6e0d0778df459a3677a7`;
- handoff control blob checksum fix:
  `041b5551ddc9fe69fd6926747a3d58a78953a047`;
- product version:
  `1.4.19+eb8f8e38b06b4aaa819b045dd0498ee4ff9681ea`;
- package ZIP SHA-256:
  `fe7b0eb665ad880d2bc36c3a9a0df1beb8f9a2094aa051148b4c108566951e37`;
- handoff manifest SHA-256:
  `8768d510493d0205e4af5bc65f66a00a1eb7320ad233f06cec0c2e8b31dd1505`.

The seven-file staging directory was additionally packaged into one pending
handoff archive on PC1 and re-expanded into a scratch directory; every inner
manifest entry validated again. The outer archive SHA-256 is
`7985d8bb6a77911f21d0c90ea6b192d399f99dceaa97c188a4a5596040a57e5d`.
This archive is **staged only** and has not been Taildrop-delivered to PC2.

The exact handoff was staged only on PC1 and all manifest entries validate. A
Windows `-PlanOnly` execution of that runner on PC1, with PC1 host/credential
pins substituted only for static exercise, returned `PLAN_PASS`: package
self-test PASS, install PlanOnly PASS, OpenCodex readiness HTTP 200, no
credential decryption and no config mutation. Evidence SHA-256:
`4e809a592269ae4daa10500b917427708301c323078a1a54ac7cdb11b85b2099`.

Therefore the remaining PC2 blocker is no longer package preparation. It is the
explicitly deferred PC2-local human/provider transition and resulting final
active-session PASS receipt.

The currently valid pending handoff is **schema version 2**. It supersedes both
the originally delivered pre-fix files and the intermediate schema-v1 staging.
It remains staged only on PC1 and has not been sent to or executed on PC2:

- qualified product revision:
  `eb8f8e38b06b4aaa819b045dd0498ee4ff9681ea`;
- ProviderSwitcher schema-v2 canary-control revision:
  `d185d00803919f2c6c3cedf7db910974738c0458`;
- schema-v2 checksum-manifest revision:
  `f5202e4b86b9f63df22572442e5556b338e5e767`;
- ProviderSwitcher owner branch documentation tip:
  `0aa29e4f`;
- product ZIP SHA-256:
  `fe7b0eb665ad880d2bc36c3a9a0df1beb8f9a2094aa051148b4c108566951e37`;
- schema-v2 handoff manifest SHA-256:
  `712605a98c95e9ff9cbc69207bed7561d2fac48d393b2cf57be10b82f2a85928`;
- outer pending handoff ZIP SHA-256:
  `89a961a476b3e7848ef39d3018d90bf0e523a403dff1d947c8ef3d05e72479f6`.

The schema-v2 collector/finalizer requires the original nine active-session
checks plus real native OpenAI and routed GLM canaries before emitting a final
PASS receipt. This exact collector was exercised on PC1 without changing the
current config and produced schema `2`, result `PASS`:

- PC1 schema-v2 receipt SHA-256:
  `3aec4fa688fe06059b5d204977f606ffd9c52b89d1c64a177238ca214c718cb7`;
- `gpt-6.1-sol` / `PC_OPENAI_OK`: PASS, `turn.completed`, zero error events,
  evidence SHA-256
  `08d06bc182fff49b6b3afa24b19ad8846ddcfca7ca8e416fe4806e6ba33083dd`;
- `dgx-glm53/glm5.3-flash` / `PC_GLM_OK`: PASS, `turn.completed`, zero error
  events, evidence SHA-256
  `7ac421df12dcc6fe2ef972756c20a330a6af00856a86f0d2de776579fb35b654`.

PC2 retirement admission now fail-closes unless the PC2 receipt is schema 2 and
both model canaries pass. A schema-1 PC2 receipt is intentionally invalid even
if all nine older active-session checks pass. The receipt is additionally bound
to the exact qualified PC2 product before it can authorize retirement:

- product version must equal
  `1.4.19+eb8f8e38b06b4aaa819b045dd0498ee4ff9681ea`;
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
on `ops/opencodex-retirement-owner-20261008`, currently `93935c4a`. The combined
retirement gate and runner suites pass 27 tests. A live `plan` execution is mutation-free and
currently reports `BLOCKED_PC2_LOCAL_CUTOVER` with exit 3 while confirming Mac
direct ingress, PC1 receipt validity, OpenCodex native OpenAI/GLM prerequisites,
WMC readiness/fences, Stable/Beta running state, zero established 2455/2456
clients, exact preserved container identities/restart policies and the expected
2455/2456 Serve targets. The runner requires the literal confirmation token plus
a valid PC2 receipt before it can stop containers or alter Serve state; partial
apply failures automatically restore the captured container/Serve snapshot.

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

This missing receipt is a hard task-4.5 retirement blocker. Idle 2455/2456
connections do not replace the missing client proof, and Stable/Beta must not be
stopped or unpublished until PC2 evidence passes.

No workspace membership mutation, q2 replay, account reauthentication, or
credential migration was performed while collecting this evidence.
