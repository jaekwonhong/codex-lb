# Design

## Cutover order

1. Revalidate OpenCodex 10101 and WMC 2461 readiness plus the Stable/Beta
   task-4.4 writer fence.
2. Collect exact current ingress evidence for Mac, PC1 and PC2. Every client
   must select `opencodex`; legacy Stable/Beta provider definitions may remain
   only as rollback profiles.
3. Confirm the OpenCodex native OpenAI provider is default and the GLM route is
   available without traversing Codex-LB.
4. Confirm there are no established client connections to host ports 2455 or
   2456. This is a drain check, not a substitute for per-client evidence.
5. Snapshot the active Stable/Beta container/image metadata and the tailnet
   serve configuration required to restore 2455/2456.
6. Stop Stable/Beta without deleting their images or rollback credentials.
7. Remove/disable active tailnet 2455/2456 ingress while leaving OpenCodex
   10101 published.
8. Verify direct OpenCodex OpenAI-pool and GLM inference, WMC readiness and
   absence of 2455/2456 listeners/data-plane traffic.

## Client evidence

Client migration is explicit. Mac and Windows Codex configurations must have
`model_provider = "opencodex"` and the OpenCodex provider must target port
10101. Windows ProviderSwitcher qualification additionally requires its normal
active-session verifier so an incomplete provider transition or resident
credential helper is not mistaken for completed migration.

PC2 cannot be inferred from Mac/PC1 state, tailnet reachability, or an idle
2455/2456 socket. Its delivered local rollout runner and normal ProviderSwitcher
confirmation remain the required proof.

## Rollback

Task 4.5 preserves rather than removes the prior Stable/Beta data plane. A
rollback restores the retained tailnet 2455/2456 serve entries, starts the exact
retained Stable/Beta containers/images, verifies health, and only then selects a
Stable/Beta ProviderSwitcher profile on the affected client.

OpenCodex account-pool state is not reverse-migrated into Codex-LB during
rollback. Stable/Beta retain their existing rollback credentials only for the
explicit rollback path. WMC production membership ownership remains unchanged.

## Separation from task 4.6

Task 4.5 stops active use but deletes nothing required for rollback. Image,
container, old provider-profile and routing-artifact deletion is deferred to
task 4.6 after final rollback evidence is frozen.
