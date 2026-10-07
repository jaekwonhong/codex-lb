# Retire the Codex-LB inference data plane behind OpenCodex

## Why

Task 4.4 moved production workspace-membership ownership to the standalone WMC,
but Codex-LB Stable/Beta are still running as inference proxies and remain
published on ports 2455/2456. Mac and PC1 already use OpenCodex directly; PC2
still requires its local ProviderSwitcher confirmation. Until every client is
proven direct-to-OpenCodex, stopping Codex-LB would risk stranding a client.

The final ownership contract requires OpenCodex to be the only active
ChatGPT/Codex request-facing account-pool and provider-routing authority.
Codex-LB Stable/Beta may remain as explicit rollback artifacts, but SHALL NOT
remain a second active production inference path after task 4.5.

## What changes

- Require exact per-client evidence that PC1, PC2 and Mac select the OpenCodex
  provider at port 10101 before retiring Codex-LB ingress.
- Require OpenCodex readiness, native OpenAI pool readiness, GLM provider
  availability, WMC readiness/quiescence and the task-4.4 legacy writer fence.
- Require no established client connection to Codex-LB 2455/2456 during the
  retirement window.
- Stop the active Stable/Beta inference containers only after all gates pass.
- Remove/disable the active 2455/2456 tailnet ingress after preserving its exact
  rollback configuration.
- Retain Stable/Beta images, stopped containers/configuration, API-key bundles
  and ProviderSwitcher rollback profiles so a deliberate rollback can restore
  the prior inference path without reconstructing credentials.
- Keep WMC and OpenCodex ownership unchanged; this task performs no workspace
  membership mutation and does not move credential ownership into WMC.

## Safety boundary

- PC2 local confirmation is a hard precondition; the absence of established
  traffic on 2455/2456 is not sufficient evidence that PC2 has migrated.
- OpenCodex remains the active inference data plane throughout the cutover.
- Codex-LB rollback artifacts are stopped, not deleted, during task 4.5.
- A rollback is explicit: restore the retained 2455/2456 ingress/container
  state and deliberately select a Stable/Beta rollback profile. There is no
  automatic fallback from OpenCodex to Codex-LB.
- The q2 membership mutation/recovery evidence is historical and SHALL NOT be
  replayed as part of this task.
