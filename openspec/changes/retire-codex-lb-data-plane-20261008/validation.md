# Validation — 2026-10-08

## Current pre-retirement state

- WMC task 4.4 remains green and owns production workspace-membership writes.
- OpenCodex 2.80.0 is ready on port 10101 with native OpenAI as the default
  provider and direct `dgx-glm53` routing.
- Mac selects `model_provider = "opencodex"` at the 10101 endpoint.
- PC1 active-session evidence is retained in `evidence/pc1-active-session.json`.
  All nine ProviderSwitcher checks pass; the receipt SHA-256 is
  `22b2e70d14f53f4434a0351ef632e79d138062997928ae74de296186aed627b6`.
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

The read-only retirement gate is retained in the OpenCodex operations branch at
`d5838c9a`. Its five unit tests pass. Against the current live runtime and the
retained PC1 receipt, it reports `BLOCKED_PC2_LOCAL_CUTOVER` with exit 3 while
confirming Mac direct ingress, PC1 receipt validity, OpenCodex native OpenAI/GLM
prerequisites, WMC readiness/fences, Stable/Beta running state and current
Tailscale Serve publication.

This missing receipt is a hard task-4.5 retirement blocker. Idle 2455/2456
connections do not replace the missing client proof, and Stable/Beta must not be
stopped or unpublished until PC2 evidence passes.

No workspace membership mutation, q2 replay, account reauthentication, or
credential migration was performed while collecting this evidence.
