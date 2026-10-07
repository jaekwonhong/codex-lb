# Workspace Member Controller production ownership

This runbook describes the qualified task-4.4 state after production workspace
membership ownership moved from legacy Codex-LB orchestration to the standalone
Workspace Member Controller.

## Runtime ownership

- OpenCodex owns inference-account credentials, pool selection, live quota,
  cooldown, request failover and thread/account affinity.
- WMC owns production workspace membership switch commands, durable effect
  ownership, unknown-effect state and no-replay reconciliation.
- FourSessionLauncher Companion remains the workspace membership effect adapter;
  it does not own the durable orchestration decision.
- Codex-LB Stable/Beta continue serving inference during migration but run with
  `CODEX_LB_WORKSPACE_MEMBERSHIP_WRITER=wmc`, so legacy member-switch writes,
  rotation-intent writes and rotation scheduler/worker effects fail closed.
- Legacy member-switch read/status and OAuth-enrollment/account-handoff surfaces
  remain temporarily present for rollback and task 4.5.

## Production WMC

Container:

```text
workspace-member-controller
```

Image:

```text
codex-lb-wmc:production-b274388da-20261008
```

The listener remains published only on host loopback port 2461, with a read-only
container root filesystem, dropped Linux capabilities, `no-new-privileges`, and
the existing owner-only WMC/OpenCodex token mounts.

Production mutation mode is explicit:

```text
WMC_MUTATIONS_ENABLED=true
```

The database principal is `workspace_member_controller_writer`. It has read
access to the Controller migration tables, `INSERT/UPDATE` on
`member_switch_control_records`, and `INSERT` on
`member_switch_command_receipts`. It has no delete privilege on those journal
tables and does not use the Codex-LB application identity.

## Legacy writer fence

Both Codex-LB instances must report:

```text
CODEX_LB_WORKSPACE_MEMBERSHIP_WRITER=wmc
```

In that mode:

- legacy member-switch run creation is rejected;
- legacy member-switch commands are rejected;
- legacy automatic-rotation intent writes are rejected;
- scheduler ticks do not elect a leader or execute a plan;
- direct legacy rotation workers reject before effect work;
- read/status and OAuth-enrollment surfaces remain available.

Do not remove this fence merely because no rotation intent or plan currently
exists. The fence is the runtime single-writer guarantee.

## Rollback

Pre-cutover containers are retained stopped:

```text
workspace-member-controller-rollback-pre-ownership-20261008
codex-lb-stable-rollback-pre-wmc-ownership-20261008
codex-lb-beta-rollback-pre-wmc-ownership-20261008
```

Rollback is permitted only while the shared membership journal has no new WMC
active/pending effect. If a WMC mutation has crossed the effect boundary, use
its durable reconciliation/recovery state; do not switch writers and resend the
same membership command.

For a clean pre-effect rollback, stop the production WMC and fenced Codex-LB
containers, restore the retained containers to their original names, and verify
the shared journal is quiescent before re-enabling legacy writer ownership.

## Verification

After any restart or cutover, verify all of the following:

- `GET http://127.0.0.1:2461/health/ready` returns WMC ready;
- Stable 2455 and Beta 2456 `/health/ready` return database `ok` and the same
  two-member bridge-ring fingerprint;
- both Codex-LB containers report writer mode `wmc`;
- OpenCodex 10101 reports ready;
- `member_switch_control_records` has no unexpected active/pending operation;
- no automatic rotation intent or legacy canary plan is enabled unless a later
  qualified WMC-owned workflow explicitly requires one.
