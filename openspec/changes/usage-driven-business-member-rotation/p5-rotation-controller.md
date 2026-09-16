# P5 — Rotation Controller

P5 starts at G1 `ce807515439a285147c807f2a83b1f221cb67626` and owns the
server-side transition from the G1 `admission_ready` boundary into the existing
durable member-switch command authority. It does not add a second membership
mutation executor and it does not enable automatic rotation.

## Durable ownership

The controller stores its restart state in an additive `rotation` payload in the
existing `member_switch_control_records` table. Rotation records do not acquire
the global member-switch effect scope. The child `run` created by
`MemberSwitchService` continues to acquire that scope and its durable command
claim remains the only authority that may call the Companion operation start.
Malformed rotation records fail local admission closed; valid rotation records
are coordination evidence and do not let automatic work bypass a manual child
run or any other active member-switch owner.

One evaluation deterministically maps to one controller id, one child run id,
and one start command id. A restart that finds a pending or already recorded
child `start` reconciles the durable receipt/client-flow lookup and never submits
another start. A retained preview with no start claim is not effect authority:
it waits for a fresh G1 evaluation and current P4 provenance before the same
child can proceed. The controller persists G1 evaluation/reset/quota references
independently of the reset-credit request pin lifetime.

## Pre-effect snapshot and session ownership

P5 calls `final_usage_snapshot_inputs()` again at the pre-effect boundary using
the exact current member and one fresh same-fetch Usage receipt. That newest
receipt's Weekly window is itself re-assessed before effect, so a member whose
Weekly usage recovered after an earlier admission cannot be removed from stale
evidence. It retains the
5H and Weekly inputs through `MemberUsageSnapshotRepository` using a dedicated
short-lived session. The snapshot repository owns its commit and lock. The
controller stores only the committed immutable snapshot ids and membership
epoch after that call succeeds. Repeating the step after a crash reuses the P3
epoch idempotently; different evidence for the same epoch is an attention state
and cannot reach member-switch `start`.

P3 quota/effect bookkeeping likewise uses a separate short-lived session. The
controller first checks that the same quota reservation is still live, then the
existing member-switch child durably claims `start` before Companion mutation.
P3 records the remove request boundary immediately after that durable child
claim; if the process dies in between, restart reconstructs the already-claimed
child and backfills the idempotent accounting before doing read-only
reconciliation. An unclaimed preview can never become a mutation from `resume()`.
That P3 row is accounting evidence, never execute permission. If the durable
child operation proves a pre-membership non-effect, the controller records
authoritative non-effect, closes the child without a Companion mutation, and
may release the reservation. Unknown effects remain reserved.

## Companion P4 gate

P4 did not add a catalog capability token or runtime provenance endpoint.
Therefore P5 requires a positively supplied provenance assertion before an
automatic mutation may begin. The supported contract is exactly:

- contract `member_rotation_typed_telemetry_v1`;
- Companion version `2.11.47`;
- binary SHA-256 `0f7b665e47f1b2cd4959814afe3ee68fe0aa5cc25a264e295997d3499290f1ce`;
- operations commit `47ac829a23b9811537bcd2d21ae9b8003c9c464a`.

Missing or different provenance fails closed before the child member-switch
start. The stored `p4_provenance_verified` presentation flag is never authority;
the exact tuple is re-qualified against the currently supported contract on
load and again before an unclaimed start. P5 does not infer support from optional telemetry fields. Python schemas
preserve P4 response observations as typed JSON primitives and keep field
absence distinct from an explicit JSON null. Capture/parse/no-response/transport
failures are attention evidence and never create replay authority.

## Candidate and settlement boundary

Candidate selection consumes only the Companion workspace catalog member list,
which is the implemented workspace candidate allowlist. It never searches the
OAuth/account pool. The owner, the outgoing identity, and every currently
observed member are excluded by exact email/user identity. The existing
member-switch create/preview/auth-catalog validation remains the readiness and
identity contract before the durable start claim.

The child operation may internally progress remove then invite. P5 therefore
does not add separate Python remove/invite calls. It projects P4 invitation
settlement and durable operation evidence into distinct `removal_*`,
`invite_*`, and `waiting_membership` states. `invitation_issued` is an invite
effect only. Controller completion additionally requires the existing
authoritative membership confirmation and P4 `final_membership_confirmed`.
An automatic child run can then be finalized through an internal durable
`finish` claim; ambiguous finalization stays in a resumable `finalizing` state
until that same claim is reconciled. Quota terminalization is idempotent for the
same already-recorded outcome, so a crash between child settlement, quota
bookkeeping, and controller publication cannot reopen or replay an effect. The
public/manual flow keeps its existing OAuth completion policy.

No P5 qualification performs a real reset-credit redemption, member removal,
invite, join, OAuth action, Companion deployment, Beta deployment, or automatic
rotation enablement.
