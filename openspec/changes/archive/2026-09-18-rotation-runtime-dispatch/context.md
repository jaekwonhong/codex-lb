# Runtime dispatch and single-evaluation scheduler — 2026-09-18

This change implements the source integration missing after Q2: current host
runtime evidence at the final dispatch boundary and a lifecycle-owned scheduler.
It does not deploy, activate or qualify a new Companion release.

## Trust boundary

`scripts/member_rotation_host_observation.py` runs outside the backend on macOS.
It requires one listener process on TCP 53418, matches its kernel-mapped text
vnode's path/device/inode to the executable, reads its SHA-256, then checks the
process start identity and file metadata again. It never launches the executable.
The resulting observation expires 30 seconds after verification began. Its
Ed25519 signature covers the release tuple, exact backend endpoint, process/file
identity and timestamps. The expected tuple is still the qualified 2.11.47 tuple;
the unqualified 2.11.48-canary.1 source candidate is deliberately rejected.

The backend reads `<data_dir>/member-rotation-runtime/host-verifier.pub` as a raw
32-byte Ed25519 public key and `host-observation.json` as the signed envelope.
The private key remains exclusively with the external host verifier. The public
key and operator plan must be protected operator-owned, read-only mounts in a
deployed backend; replacing the trust root is a release operation. No keys,
runtime mount, periodic signer process or active plan were provisioned here.
The producer CLI accepts explicit binary, endpoint, provenance, private-key and
output paths and atomically publishes the envelope. Running it once is not a
continuous attestation service.

Signatures establish who observed a runtime at a recent time, not that the
process can never change afterward. The residual observation-to-send interval
is bounded by 30 seconds, includes no awaited application work after final
validation, and is not a transactional process lock. In-place replacement,
listener changes or stopped renewal invalidate subsequent receipts or let them
expire. This macOS producer has a real host smoke check plus synthetic failure
tests; it is not a Windows producer.

## Dispatch ordering

The controller defaults to a rejecting provider. A supplied P4 tuple or cached
presentation flag alone cannot grant dispatch. After the child's durable start
claim and quota write, the controller rechecks the plan/workspace guard, fresh
Weekly evidence and the externally signed runtime observation immediately before
start. A validation failure records a local non-effect and returns the quota
reservation through existing cleanup. Cancellation or uncertain I/O retains the
durable claim for reconciliation.

Automatic commands require the two canary/managed-remove capability tokens and
always select the dedicated canary endpoint. Manual commands retain their normal
route. Thus the running 2.11.47 binary cannot become a canary simply by supplying
a valid host observation; the candidate must first undergo matched release
qualification and the reviewed qualification tuple must be updated.

## Scheduling and one-evaluation retention

The application starts/stops `RotationScheduler`. A missing or disabled
`<data_dir>/member-rotation-runtime/canary-plan.json` causes no DB, leader-election,
Usage, reset or membership work. The plan uses the `CanaryPlan` schema: explicit
enablement, one evaluation UUID, exact workspace/account/outgoing identity,
membership epoch, expiry and qualified provenance. No new environment knob or
dashboard effect authority is introduced. Workspace operator intent must also
be enabled and match the exact workspace identity.

An enabled tick enters the existing leader gate and local lock. It obtains exact
current membership and fresh same-response P1 evidence. Only an exhausted Weekly
window admits the globally unique `rotation-q3-single-evaluation` binding row.
The row is stored in the existing control table with kind `rotation_schedule`,
without migration or membership-scope authority. It blocks a second evaluation
or changed plan across workers/restart. Admission validates this known passive
record type; older backends treat it as unknown and therefore fail closed.

Reset and quota IDs derive from the immutable evaluation UUID. P2 uses the central
serialized reset authority; afterward fresh P1 evidence and exact membership
are obtained again before P3 admission and P5. A legitimate reset recovery ends
without quota reservation or membership mutation. Existing controllers are
reconciled rather than given another reset/evaluation attempt. A crash after the
binding but before controller creation stays blocked for operator review. There
is no timeout, deletion, plan replacement or automatic recovery that replenishes
this evaluation budget. Retain this row, controller/quota rows and the Companion
canary receipt store across rollback.

The guard checks plan equality and expiry both before and after the awaited
workspace-intent query. For example, deleting the plan while the final DB query
waits prevents Companion start and returns the local quota request as non-effect.
Cooperative cancellation is propagated; a cancellation already requested on the
worker also blocks a later guard, even if an upstream helper swallowed it.
This is a bounded Q3 scheduler, not an unrestricted recurring rotation rollout.

## Qualification and provenance

- Updated `scripts/qualify_usage_member_rotation.sh`: 354 passed, Ruff and ty passed.
- New runtime/scheduler/host cases: 32 passed (included in the 354).
- Five actual application lifespan/startup integration cases passed in the
  separate runtime/lifecycle run (34 cases before the final three regressions).
- `app/main.py` Ruff and ty checks passed.
- Independent reviewer `/root/q3_readiness`: PASS after independently reproducing
  the plan-change-during-intent-query race and verifying the final fix.
- Read-only host smoke verification passed for PID 85994, 2.11.47 and the exact
  historical qualified SHA-256. The saved observation is unsigned historical
  evidence, is not installed at the runtime path, and is not dispatch authority.

Evidence is preserved in the operations workspace at
`artifacts/rotation-runtime-dispatch-20260918/`. Backend changes remain uncommitted
on baseline `4acf0d9fffd99b5c8677dbed5df460c5ef04f7bd` alongside earlier verified
dispatch and canary changes. No production state was changed.

## Next release work

Build and independently qualify the matched backend/2.11.48-canary.1 artifact,
review its new release identity, and follow the production deployment policy.
Provision the external signer/trust root and mounts while keeping the plan and
workspace OFF. Qualify renewal, revocation, rollout and rollback with retained
stores before any activation. Only legitimate exhausted Weekly usage unresolved
by reset credit may eventually justify at most one live Q3 canary. Q3 and Q4
remain open.
