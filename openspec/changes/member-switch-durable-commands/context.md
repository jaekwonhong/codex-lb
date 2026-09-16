# Control ownership, recovery and qualification

## Scope and inputs

This change extends the separately verified `simplify-beta-member-switch`
candidate, not the stale 1.23 vendor working tree. That earlier change's UI
contract is updated here to allow a **stored-status GET**, not lifecycle-driven
commands. The running beta, operational data and previous candidate are unchanged.

Companion input is the selected project's existing WIP snapshot at
`3fdb33d67d7bfd2553437198fc73bce2b3c38665`, with its pre-existing local modifications
included in the input hash manifest. It is not represented as the identity of a
currently deployed Companion executable.

## Owners and execution path

```
Accounts UI: run locator and last rendered view
    -> codex-lb: authenticated command, expected revision, command UUID
        -> application DB: global run admission + command receipt
            -> Companion: membership/browser child operations
            -> durable auth adapter: OAuth/auth child state
        <- persisted result + permitted next actions
    <- display only
```

The backend owns the **overall run**, not every participant's private state.
Companion owns its membership execution receipt. The auth adapter stores its
child snapshot in the same application DB. A frontend receipt is not evidence
that a participant completed its work. Fine-grained diagnostic codes do not
grant transition permission.

`member_switch_control_records.active_scope` admits one overall run across
instances. Short compare-and-swap transactions persist intent before effects;
the transaction is never held over network or browser work. A separate receipt
table keeps command UUID/fingerprint history. An old UUID cannot become a new
command by changing its action or expected revision. Exact repeats return the
current recorded view rather than replaying effects.

No expiry, browser shutdown, missing reply, or 404 implicitly releases a run.
Concurrent read-only reconciliation uses participant evidence and a revision CAS,
so a stale writer cannot overwrite a later result. A pending command can mean
either still executing or interrupted; the UI does not guess which from age.

## API and manual phases

`GET /api/member-switch-runs/active`, `GET /api/member-switch-runs/{id}` and
`GET /api/member-auth-handoffs/{id}` read stored state only. The latter uses a
separate read dependency: it does not even construct OAuth writers or token
encryption objects. Private responses use `Cache-Control: no-store`.

`GET /api/member-switch-runs/catalog` reads Companion metadata. These member/owner
identity surfaces and all progress commands require `accounts:write`. The single progression
endpoint is `POST /api/member-switch-runs/{id}/commands`, with `commandId`,
`expectedRevision` and `action`. There is no second unfenced raw advance endpoint.
Legacy raw handoff preparation/reconciliation cannot bypass managed-run admission.

```
previewed -> membership_requested -> membership_confirmed
          -> auth_prepared -> auth_browser_opened -> auth_confirmed -> completed
```

`auth_browser_opened` is optional when authorization was completed separately.
Exceptions surface as `failed`, `needs_attention`, or `outcome_unknown`; the
backend's `allowedActions` determines what may happen next. `observe_auth` reads
the stored child snapshot. `advance_auth` may check OAuth, delete verified outgoing auth
or reissue an expired device code and is separately confirmed in the UI.

Preparation quarantines outgoing auth. Deletion waits for exact incoming auth
verification in an explicit advance command. A membership success is therefore
not a completed auth handoff. Browser cleanup and finalization are separate steps.

## Companion repair and responsibility split

The input WIP called a simplified `RunAsync` while keeping a disconnected
`RunGuardedAsync` with identity/removal/settlement checks. The former caused
29 failures in the unchanged selected fake-driver suite. The abandoned runner
was removed and there is now one canonical guarded workflow.

`MembershipDecision` is pure. `MembershipInspection` owns typed observations;
`MembershipMutation` owns exact removal verification. Existing recipient-session
and OAuth-browser services remain their own participants. `MemberSwitchOperationStore`
owns persisted client-flow bindings and progress receipts. This is a focused
split, not a rewrite of every Chrome interaction or all of MemberSwitchService.

Production Companion advertises `durable_client_flow` only when persistent
receipt storage is configured. Start requires a client-flow UUID in that mode.
The receipt stores a preview hash, never the raw preview token. File updates use
a private temporary file, flush, and atomic rename before publishing state.
The existing one-Launcher-instance-per-profile boundary remains mandatory.

`GET /member-switch/v1/client-flows/{id}` returns a read-only Start receipt.
Reconstruction marks unfinished membership as `needs_attention` rather than a
releasable failure. A later Start cannot silently take over a terminal owner.
Finalization retains a tombstone so a lost parent response can be reconciled.

Release ordering is receipt-first, then coordinator release. Lookup reports
`operation_finalized` only when the receipt is present and the coordinator no
longer owns that operation. Receipt-write failure therefore leaves ownership
intact. Interruption between the two writes remains retained rather than falsely
completed; it is not evidence permitting the parent to replay finalization.

CAS methods return the immutable snapshot obtained by their own UPDATE RETURNING,
not a new SELECT after commit that could adopt another writer's revision.
An admitted membership failure is `needs_attention`, not a releasable reset.
Auth advancement also rechecks partial target-identity collisions before deleting
quarantined outgoing auth. A reissued device code can be used by explicitly
closing and reopening the owned browser; closing does not complete the run.

## Recovery matrix

| Interrupted boundary | Evidence used | Result |
|---|---|---|
| Browser reload / cleared locator | Backend active-run GET | Restore display, no command replay |
| Preview response loss | Stored run with no membership request | Explicit cancel is safe |
| Membership Start reply loss | Companion client-flow receipt and exact operation identity | Explicit reconciliation, no second Start |
| Completed auth child reply loss | Stored child snapshot and matching last command UUID | Explicit reconciliation |
| Finalize reply loss | Exact Companion finalized tombstone | Release parent only after proof |
| Release receipt stored, coordinator release interrupted | Receipt plus still-held coordinator owner | Keep retained; separate review, no automatic replay |
| Membership process interruption | Retained operation marked needs attention | Block new work |
| Recipient session / browser open or close without a complete receipt | No authoritative completion receipt | Keep pending; manual review required |
| OAuth start/delete/reissue interrupted inside the external effect | Persisted intent/checkpoint but no complete receipt | Keep pending; do not repeat on reconstruction |

The last three rows are intentionally not a universal auto-recovery mechanism.
An operator cannot clear them merely by pressing retry. No unsafe force-release
or TTL takeover endpoint is supplied.

## Automatic rotation decision: NOT QUALIFIED, remains disconnected

Stored reads, duplicate submission, command history, cross-instance CAS,
receipt-backed restoration and explicit manual transitions have offline coverage.
This is sufficient for further review of the manual candidate, not for unattended
operation. Browser/session and mid-OAuth interruption still lack complete child
receipts, and deployed identity/cross-lane rollout is not verified.

Consequently no automatic consumer, timer, usage-triggered switch, focus retry,
or reconnect recovery has been reintroduced. Existing usage-event producer and
legacy endpoints are not described as an enabled scheduler. Any future worker
must use the same backend run/command admission, and must first qualify every
non-idempotent interruption boundary. Pure ranking code is not that qualification.

## Rollout and limits

The candidate requires a coordinated backend/Companion/UI update and the two
pre-existing local extension tables, `member_switch_control_records` and
`member_switch_command_receipts`. The beta.9 rebase deliberately does not carry
the historical local Alembic branch that first created those tables; the official
beta.9 migration graph remains authoritative. A deployment must therefore verify
that the retained extension tables and their data survive the upstream migration,
and must fail closed if they are absent rather than inventing a second migration
owner. Beta is not the shared DB migration owner. Stop old automation clients/tabs
before any future rollout. Existing direct Companion clients are not magically
fenced by the new backend's DB. Missing capability or catalog mismatch blocks the
new path before membership mutation rather than falling back.

Old in-flight runs, browser IDs, quarantined auth, existing catalog overlays,
actual Docker-to-Mac transport, real OAuth, Safari/WebKit, native-AOT publication,
power-loss filesystem guarantees and PostgreSQL concurrency have not been
live-qualified. Tests use temporary SQLite, reconstructed instances, fault
injection and fake browser/OAuth drivers. No deployment or operational reset is
part of this change.
