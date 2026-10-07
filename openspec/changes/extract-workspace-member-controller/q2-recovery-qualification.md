# q2 partial-effect recovery qualification

Date: 2026-10-07, revalidated read-only on 2026-10-08.

## Decision

The single-workspace mutation canary qualification is complete. The q2 forward
was not successful, but its partial effect was recovered through the separately
qualified purpose-bound recovery path exactly once. No additional forward,
rollback, or recovery effect is authorized by this evidence.

## Retained forward evidence

The q2 forward receipt remains terminal:

```text
stage=failed
code=acceptance_settlement_not_observed
membershipState=unknown
purpose=forward
released=true
finalMembershipConfirmed=false
pendingInvitation=true
```

`released=true` does not rewrite the failed result. The parent became releasable
only after the recovery child proved restoration. Confirmed q2 removal and the
issued target invitation remain part of the immutable historical receipt.

## Recovery child evidence

Recovery child:

```text
operationId=7b1c932ec4ec4ce59e557c2b96834a64
stage=completed
code=member_added
membershipState=active
purpose=partial_recovery
released=true
recoveryCleanupClaimed=true
recoveryCleanupConfirmed=true
recoveryInviteClaimed=true
finalMembershipConfirmed=true
pendingInvitation=false
```

Its trace contains `recovery_target_invite_absence_observed` before restoration
invitation and terminates with `member_added` after final membership settlement.

## Durable Companion evidence

Current retained receipt store:

```text
schemaVersion=3
receiptCount=5
sha256=f35900a6d0d3929fb35cb443df8805820f511819cc5458d43f36c37cb670fd89
```

Recovery-capable Companion executable retained in the running
FourSessionLauncher installation:

```text
sha256=d9ca8edb40497fd45e285bc32262b5f3ea7d6a47fee787994ea45e5784b810d0
```

The recovered schema-3 receipt store contains the purpose-bound recovery shape
and therefore must not be interpreted as downgrade-compatible merely because
its numeric schema version remains 3.

## Fresh restoration revalidation

Read-only observation of the exact canary workspace on 2026-10-08 returned:

- `available=true`, `code=ok`;
- complete and owner-verified;
- no ambiguous, partial, duplicate, or unknown identity;
- exactly two observed members: the workspace owner and the restored original
  allowlisted non-owner member;
- no failed target member.

The restored original member's normalized-email SHA-256 prefix is
`04722dd289b0`, matching the recovery child's target identity without recording
the raw email in this evidence file.

## Controller/recovery release

A read-only query of the shared Controller membership journal returned zero rows
with `active_scope` or `pending_action`. Companion admission also reports no
active operation. This proves recovery did not leave retained mutation ownership
after the original member was restored.

## No-replay closeout

The q1 and q2 forward budgets remain spent. The q2 forward marker and durable
receipts are no-replay authority, not cleanup artifacts. The partial recovery
child is also terminal and MUST NOT be started again. Subsequent WMC extraction
work starts at task 4.4 from the restored state.
