# Validation — 2026-10-08

## Source and runtime candidate

- implementation commit: `8201a15b3`
- base shadow image: `codex-lb-wmc-shadow:3e2e9e02`
- reconciliation image:
  `codex-lb-wmc-shadow:reconciliation-8201a15b3-20261008`
- image digest:
  `sha256:faeb6e6d7fb969e545b63e9b1070c47a878dba0150b9473dbdaf9d42ecd33626`

The candidate overlays only the three Controller modules that implement or use
the reconciliation fence: `account_state.py`, `standalone_runtime.py`, and
`rotation_decision.py`. SHA-256 comparison of each file inside the built image
matched the committed worktree copy.

## Contract behavior

The reusable stable-read helper reads one exact `opencodex_account_id` twice and
accepts the second projection only when both reads agree on:

- exact account id;
- pool credential generation;
- native-main identity generation;
- deterministic `stateRevision`.

Standalone readiness additionally requires the accepted projection to be no
older than 30 seconds. It intentionally does not require
`selectionState=selectable`: durable account identity remains valid while an
account is paused, reauth-required, quota-exhausted, or otherwise excluded from
inference selection.

Quota-driven rotation uses the same stable-read fence before reserving
Controller-owned membership mutation budget. Pre-effect account-evidence
revalidation also uses it, then requires the accepted generation/revision to
match the immutable admission evidence.

## Automated validation

Focused adapter/standalone/rotation tests:

```text
33 passed
```

All Workspace Member Controller unit tests:

```text
85 passed
```

Static gates:

- `ruff check` on the WMC module and WMC unit tests: PASS
- `ty check` on the WMC module and affected tests: PASS
- `git diff --check`: PASS
- PC1 OpenSpec CLI strict validation of this change: PASS
- strict validation of all active OpenSpec changes: `94 passed, 0 failed`

Regression coverage includes:

- stable fresh exact-account projection;
- adjacent-read `stateRevision` race;
- stale projection;
- stable paused/reauth/excluded binding remaining readiness-valid;
- rotation refusing an unstable projection before budget reservation;
- pre-effect evidence revalidation refusing a transition between adjacent reads;
- preservation of the pre-existing exact-account identity-mismatch error.

## Live OpenCodex/WMC validation

No live workspace membership or OpenCodex account-routing state was changed.
The retained canary binding snapshot was used only by a one-shot read-only
`--validate` container.

Against live OpenCodex 2.80 on port 10101, the retained two bindings include one
currently excluded account and one currently selectable account. Their prior
projection qualification showed stable generation and `stateRevision` across
adjacent reads. The reconciliation candidate completed:

```text
workspace-member-controller validation passed: workspaces=3 bindings=2 opencodex_accounts=2
```

This result was obtained once before shadow promotion and once again after
promotion using the exact live image.

## Shadow promotion and rollback

The live shadow had zero bindings and no established 2461 connection at
cutover. The existing admin-token-corrected container was stopped and retained
as:

```text
workspace-member-controller-shadow-rollback-pre-reconciliation-20261008
```

The candidate was started with the same environment, read-only root filesystem,
tmpfs, dropped capabilities, `no-new-privileges`, loopback publish, PostgreSQL
socket, binding file, Companion configuration, and read-only OpenCodex
`admin-api-token` mount.

Post-promotion readiness is:

```text
status=ready workspaces=3 bindings=0 opencodex_accounts=0
```

The retained two-binding one-shot validation then passed again. Live binding
count intentionally remains zero, so this change does not authorize or perform
any workspace membership effect.

## Decision

The stable exact-account reconciliation fence is qualified for the WMC shadow.
OpenCodex remains the authority for account selection, pause/reauth, quota,
cooldown and request failover; WMC only proves exact stable account evidence
before using it for membership policy.
