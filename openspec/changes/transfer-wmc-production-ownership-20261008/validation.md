# Validation — 2026-10-08

## Source commits

- `ffb8eaf21` — mutation-enabled standalone WMC production writer.
- `b274388da` — Codex-LB legacy membership-writer fence.

The changes are stored only in the user's fork feature branch. No upstream PR
was created.

## Automated validation

Focused production-writer validation:

```text
38 passed
```

WMC + member-switch + rotation regression:

```text
174 passed, 1 skipped
```

The skip is the pre-existing external Companion static-surface qualification;
Companion provenance is qualified separately.

Static gates:

- `ruff check`: PASS
- `ty check` on the WMC production-writer boundary and affected tests: PASS
- `git diff --check`: PASS
- OpenSpec CLI `@fission-ai/openspec@1.10.0` at exact commit `50e8e5f72`:
  - `transfer-wmc-production-ownership-20261008 --strict`: PASS
  - `extract-workspace-member-controller --strict`: PASS
  - all active changes strict: `95 passed, 0 failed`

The PC1 DevSpace connector was temporarily unavailable for the final strict
gate, so the same repository-recorded OpenSpec CLI version was executed directly
against the exact Mac commit instead. No project or runtime state was changed by
that validation.

Coverage includes normal `/operations` production effect routing without canary
flags, observational reconciliation without resend, WMC bearer/auth and
switch-only action gates, mutation-enabled read-only DB rejection, legacy manual
writer rejection, rotation-intent rejection, inert scheduler behavior and a
direct-worker pre-effect fence.

## WMC candidate qualification

Production image:

```text
codex-lb-wmc:production-b274388da-20261008
sha256:29d4a94ba5266ad509e200721a348a15760d622e6ccda1ab40b8a5fcb232a7b5
```

All six overlay source files matched the committed worktree SHA-256.

A dedicated PostgreSQL role was created:

```text
workspace_member_controller_writer
default_transaction_read_only=off
```

Qualified privileges include `SELECT/INSERT/UPDATE` on the control journal,
`SELECT/INSERT` on command receipts, read access to the remaining Controller
migration tables, and no journal DELETE privilege.

Mutation-enabled one-shot validation passed twice before promotion:

```text
workspaces=3 bindings=0 opencodex_accounts=0
workspaces=3 bindings=2 opencodex_accounts=2
```

The second run reused the retained exact two-binding qualification snapshot and
therefore re-proved exact OpenCodex identity/reconciliation with production
mutation mode enabled.

## WMC promotion

The previous shadow was retained as:

```text
workspace-member-controller-rollback-pre-ownership-20261008
```

The production container is:

```text
workspace-member-controller
```

Post-promotion checks:

- readiness `200`, workspaces 3, live bindings 0;
- database user `workspace_member_controller_writer`;
- `transaction_read_only=off`;
- unauthenticated mutation request `401`;
- authenticated but unqualified `add` request `409
  mutation_action_not_qualified`;
- missing mutation lookup `404 mutation_operation_not_found`;
- control/receipt row counts unchanged across the gate probes;
- active/pending membership journal rows remained zero.

No workspace membership effect was executed during the production cutover.

## Legacy Stable/Beta fence

Stable image:

```text
codex-lb-stable:wmc-writer-fence-b274388da-20261008
sha256:5d3997120a1b324291308f6aac4b1b58296c654dc384355c1d09ed0cf385b3a5
```

Beta image:

```text
codex-lb-beta:wmc-writer-fence-b274388da-20261008
sha256:e7f6ba08c226e1ac83e1cd25de0e34041af69585540cbe894cca2e724f115702
```

For both images, every overlaid fence file was byte-identical to the tested
`b274388da` copy, while the base image retained its existing Astra/GLM patches.

The pre-cutover containers were retained stopped as:

```text
codex-lb-stable-rollback-pre-wmc-ownership-20261008
codex-lb-beta-rollback-pre-wmc-ownership-20261008
```

Stable was cut over while idle. Beta had one persistent remote client TCP
connection with discrete completed `200 OK` Codex responses. It was restarted
gracefully with a three-second stop window; the client established a new TCP
connection automatically and subsequent Codex requests again completed `200
OK`.

After both promotions:

- Stable and Beta report `workspace_membership_writer=wmc`;
- Stable/Beta `/health/ready` both report database `ok`;
- bridge ring converged to size 2 with one common fingerprint;
- OpenCodex 10101 remains `ready=true`;
- WMC membership journal active/pending count is zero;
- enabled legacy rotation-intent count is zero;
- no legacy canary plan is present.

## Ownership decision

Production workspace-membership effect ownership is now the standalone WMC.
Codex-LB remains temporarily in the inference path for the next migration task,
but its legacy workspace-membership writer paths are fenced. OpenCodex continues
to own inference-account runtime state and routing; this cutover did not move or
duplicate that authority.

## Integrated-session revalidation

The consolidated 2026-10-08 owner session revalidated the remote canonical
baseline at `c8be81e59` before beginning task 4.5. The reconciliation closeout
`6aa3a23bb` and q2 recovery closeout `54a2fd605` are strict ancestors of that
baseline; no q2 mutation or recovery action was replayed.

Current live checks remained green:

- WMC `WMC_MUTATIONS_ENABLED=true`, ready on loopback port 2461;
- database user `workspace_member_controller_writer`, transaction read-only
  `off`, required journal insert/update privileges present, journal delete
  privileges absent;
- active membership operations `0`, pending WMC mutations `0`, enabled legacy
  rotation intents `0`;
- Stable/Beta both report `CODEX_LB_WORKSPACE_MEMBERSHIP_WRITER=wmc`, matching
  two-node bridge-ring fingerprint and database-ready status;
- OpenCodex port 10101 remains ready;
- retained pre-ownership WMC/Stable/Beta containers remain stopped for rollback.

Source revalidation from the dedicated consolidated worktree produced `431
passed, 1 skipped` across the WMC/member-switch/member-rotation unit suites. The
single skip remains the external Companion static-surface provenance test.
`ruff`, focused `ty`, `git diff --check`, and strict validation of this change
and `extract-workspace-member-controller` all pass. A test-only typing cleanup
uses the Python field name for the aliased rotation-intent request and explicitly
casts an intentionally unreachable fake service; runtime behavior is unchanged.
