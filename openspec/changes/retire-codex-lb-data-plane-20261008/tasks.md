# Tasks

## Qualification

- [x] Revalidate task-4.4 WMC production ownership and legacy writer fencing.
- [x] Revalidate Mac direct OpenCodex ingress.
- [x] Revalidate PC1 direct OpenCodex ingress.
- [ ] Complete and verify PC2 local OpenCodex ProviderSwitcher transition.
- [x] Verify OpenCodex native OpenAI pool is default and GLM routes directly.
- [x] Verify no current established client connection uses 2455/2456.

## Retirement

- [ ] Freeze exact Stable/Beta container/image and tailnet 2455/2456 rollback
  configuration immediately before cutover.
- [ ] Stop active Stable/Beta inference containers after all client gates pass.
- [ ] Remove/disable active tailnet ingress for 2455/2456 while preserving
  OpenCodex 10101 ingress.
- [ ] Verify OpenCodex OpenAI-pool and GLM inference after retirement.
- [ ] Verify WMC remains ready, membership journal remains quiescent and no
  legacy membership writer has been re-enabled.

## Closeout

- [ ] Record PC1/PC2/Mac final ingress evidence and rollback receipts.
- [ ] Mark extraction task 4.5 complete only after the active Codex-LB data
  plane is stopped and direct OpenCodex qualification is green.
- [ ] Preserve all rollback artifacts for task 4.6; delete none in task 4.5.
