# Workspace Member Controller shadow runbook

This runbook applies to the qualified **read-only** shadow deployment. It is not a production cutover procedure and it does not enable membership mutation.

## Qualified runtime boundary

The shadow Controller is expected to be visible only at:

```text
http://127.0.0.1:2461
```

The container name is:

```text
workspace-member-controller-shadow
```

The qualified outer boundary publishes only host loopback even though the container process explicitly opts in to `0.0.0.0` inside its private Docker network namespace. The container uses a read-only root filesystem, drops all Linux capabilities, enables `no-new-privileges`, and uses a dedicated PostgreSQL read-only role.

The qualified Companion observation source listens on `127.0.0.1:53418`. During this shadow qualification it was started from the already installed, previously qualified FourSessionLauncher binary because its LaunchAgent was disabled. It is not required by Codex-LB inference traffic.

### OpenCodex management secret invariant

The file mounted at `/run/secrets/opencodex-admin-token` **must** be the
OpenCodex management `admin-api-token`. Do not mount `service-api-token` at this
path. The service token is a data-plane admission token and is intentionally
rejected by the Controller's exact-account management projection.

On this host the qualified source is:

```text
~/Library/Application Support/codex-lb-opencodex-router/opencodex-home/admin-api-token
```

The mount remains read-only and the source file must remain owner-only (`0600`).
Verify the source identity without printing the token:

```sh
docker inspect workspace-member-controller-shadow \
  --format '{{json .Mounts}}'
stat -f '%Sp' \
  "$HOME/Library/Application Support/codex-lb-opencodex-router/opencodex-home/admin-api-token"
```

When account bindings are non-empty, readiness is expected to exercise
`GET /api/codex-auth/controller-account-state?accountId=...` for every distinct
bound OpenCodex account. A shadow with zero bindings does not exercise that
endpoint, so `bindingCount=0` by itself is not evidence that this secret mount is
correct.

### Exact-account reconciliation fence

For every retained binding, current readiness performs two consecutive exact
OpenCodex account-state reads. The binding is reconciled only when both reads
name the same account and have the same credential/main generation plus the same
opaque `stateRevision`; the accepted second projection must also be no older
than 30 seconds.

Readiness does **not** require the bound account to be selectable. A stable
paused, reauth-required, quota-exhausted, or otherwise excluded account remains
a valid durable binding. OpenCodex continues to own inference eligibility and
routing; WMC interprets those states only inside membership-rotation policy.

An unstable or stale bound-account projection must make readiness fail closed.
Do not repair that failure by changing the binding to another account unless an
independent, qualified exact-identity binding workflow authorizes the change.

## Health checks

```sh
curl -fsS http://127.0.0.1:2461/health/live
curl -fsS http://127.0.0.1:2461/health/ready
```

Expected readiness is `status=ready`. A zero binding count is valid for read-only shadow mode.

Check that the host publish remains loopback-only:

```sh
docker inspect workspace-member-controller-shadow \
  --format '{{json .HostConfig.PortBindings}}'
```

Check the database role remains read-only:

```sh
docker exec codex-lb-postgres \
  psql -qAt -U workspace_member_controller_shadow -d codex_lb \
  -c 'SHOW default_transaction_read_only;'
```

Expected output is `on`.

## Account-state validation with retained bindings

Before enabling any account-dependent Controller stage, run the standalone
`--validate` path with a retained, read-only binding snapshot. This is a
read-only validation: it checks the migration database, Companion catalog,
binding/member identity, OpenCodex readiness, and each exact OpenCodex account
projection; it does not execute membership mutation.

The 2026-10-07 follow-up qualification used the retained two-binding canary
snapshot and completed with:

```text
workspace-member-controller validation passed: workspaces=3 bindings=2 opencodex_accounts=2
```

Do not copy those canary bindings into the live shadow merely to make its normal
readiness non-zero. Use them only in an isolated validation container unless a
separately authorized stage changes the live binding set.

## Stop the shadow only

Stopping the standalone shadow does not require a Codex-LB Stable/Beta/PostgreSQL restart:

```sh
docker stop workspace-member-controller-shadow
```

Because the container uses `restart=unless-stopped`, an explicit operator stop keeps it stopped across Docker restarts until it is explicitly started again.

To resume the same qualified container:

```sh
docker start workspace-member-controller-shadow
```

## Remove the shadow runtime

For a full shadow rollback while preserving evidence/secrets on disk:

```sh
docker rm -f workspace-member-controller-shadow
```

Do **not** delete the runtime directory or its token/evidence files merely to roll back service execution. Keeping them preserves investigation and reproducibility data.

The dedicated database role is inert when the shadow is stopped and may safely remain for later shadow/canary work. If the shadow is permanently retired, remove the role only after the container is gone:

```sql
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
  FROM workspace_member_controller_shadow;
DROP ROLE workspace_member_controller_shadow;
```

Run the SQL as the existing database owner/administrator. Dropping this dedicated role is optional for service rollback; it is not required to restore Codex-LB behavior.

## Stop the temporary Companion shadow source

The qualification session wrote the process id to:

```text
~/Library/Application Support/codex-lb-gateway/workspace-member-controller-shadow/companion.pid
```

Before stopping it, verify that the saved PID still identifies the installed FourSessionLauncher and owns the local Companion port. Do not kill a PID solely because the number is present in the file.

Example verification:

```sh
PID="$(cat "$HOME/Library/Application Support/codex-lb-gateway/workspace-member-controller-shadow/companion.pid")"
ps -p "$PID" -o pid=,comm=,args=
lsof -nP -a -p "$PID" -iTCP:53418 -sTCP:LISTEN
```

If both checks identify the qualification-owned FourSessionLauncher process, stop it gracefully:

```sh
kill "$PID"
```

No LaunchAgent needs to be disabled as part of this rollback; the pre-existing FourSessionLauncher LaunchAgent was already disabled before qualification.

## Rollback invariant

A shadow rollback is complete when all of the following are true:

- `workspace-member-controller-shadow` is stopped or absent;
- nothing listens on host port `2461`;
- if the qualification-owned Companion was stopped, nothing listens on `53418` from that process;
- Codex-LB Stable, Beta, and PostgreSQL remain running with their prior containers;
- no membership mutation has been executed by the shadow;
- no production account-routing ownership has moved from its pre-shadow state.

Do not proceed from this runbook directly to production ownership transfer. The next permitted stage is the separately authorized one-workspace mutation canary with its own rollback evidence.
