# Legacy fencing and cutover contract

Parent: `artifacts/member-switch-participant-receipts-20260906`. This candidate is
incremental and does not install, deploy, migrate operational data or enable automation.

## Executable surface

`MemberSwitchEndpoints` is the sole production member-switch route registration.
The HTTP boundary runs after routing and checks endpoint metadata, not a second
string-pattern route registry. Untagged endpoints fail closed, including newly
added mappings, case variants, and unknown legacy URLs. Existing Host, Origin,
port and path checks remain outside it. No permissive CORS or authentication
fallback is introduced.

| Route suffix under `/member-switch/v1` | Contract |
|---|---|
| GET catalog, admission, account-pool | Stored metadata only |
| GET client-flows/{id}, operations/{id}, participant-commands/{id} | Stored evidence only |
| POST previews | Explicit browser-backed preview, idle admission required |
| POST operations | Durable membership admission |
| POST operations/{id}/finalize | Explicit managed release, no orphan/legacy takeover |
| POST participant-commands | Durable session/open/close admission |

All four POST routes require `X-Member-Switch-Protocol: managed_member_switch_v1`.
The Python adapter sends it. The matching capability is checked before new work.
The header is NOT a secret or proof that a local process is the authorized backend.
It prevents unchanged older clients from using still-existing command URLs. A
malicious local process that copies the marker remains outside this compatibility
boundary; deployment must retain local access controls and stop old writers.

The following old surfaces are not mapped: cleanup, recovery authorization,
account-pool edits/open/prepare/workspace-hold/personal-cleanup, owned-workspace
discovery, workspace-group creation/configuration/archiving, candidate creation
and activation, workspace observations/resolution, notifications, and the three
earlier raw session/browser writes. Both browser-backed GETs are retired: calling
something GET did not make it a stored read. Internal browser services used by the
canonical membership runner remain intact; this is not a rewrite of their logic.

Backend `/api/member-auth-handoffs` mutations (prepare, reconciliation, catalog
registration, rotation claim/settle) are refused by a router dependency before
writer construction. Framework JSON validation may reject a malformed request
even earlier. Existing stored status and read endpoints remain available. Ordinary
OAuth/account APIs elsewhere are not renamed or globally blocked by this change.

Local Launcher `/api` HTTP mutations share the participant admission gate and are
refused while retained member/participant work exists. This includes reset, open,
configuration writes and HTTP exit. Stored reads remain available. The gate covers
the complete Launcher request and also serializes preview/start/participant/release;
it is not a process-wide lock over manual OS actions, CLI `--open`, startup config
normalization or unrelated processes.

## Existing state: preserve, classify, do not auto-adopt

The flow coordinator reconstructs a needs-attention view in memory without writing
the source file. Membership reconstruction no longer mirrors that view into the
receipt file. Incompatible or corrupt store schemas still fail construction; that
failure must not be treated as an empty store or an invitation to delete the files.

| Evidence | Decision |
|---|---|
| No retained run, quarantine, child or Companion state | Eligible to request a new preview, not permission to deploy |
| Current-version active run and matching Companion receipts | Existing explicit commands/receipt reconciliation remain available |
| Unversioned/foreign-version in-flight backend run | Display `legacy_run_review_required`, no executable actions, preserve payload/revision |
| Completed unversioned run | Historical display only; not adopted and not itself a new-run blocker |
| Current-version run without active scope | `orphan_run_retained`; no command or inferred re-acquisition |
| Legacy Companion owner without client-flow receipt | Block preview/start/legacy finalize; retain owner |
| Unreleased membership receipt without owner | Block new work and finalize; missing owner is not release evidence |
| Pending/open participant records | Prior receipt contract remains in force, including runtime-binding limits |
| Quarantined outgoing auth, incomplete or unreadable child record | Block new work; no token deletion, reactivation or inference from account status |

Backend `GET /api/member-switch-runs/admission` returns stored blocker kinds, IDs
and codes only. It constructs no OAuth or Companion writers and performs SELECTs.
Companion `GET /member-switch/v1/admission` reports retained owner/receipt state
without browser I/O. These are diagnostic reads, not admission leases. Actual
create/start checks repeat the relevant checks. The unique active scope and CAS
continue to arbitrate concurrent new backend writers.

The new `control_protocol` marker is set only by run creation. There is no automatic
backfill into old JSON and no new DB migration. Unversioned records from earlier
review candidates are intentionally not silently trusted either. IDs, command
fingerprints, auth records and catalog mappings must not be edited just to satisfy
the gate. Browser-only legacy memory with no durable trace cannot be reconstructed
from an empty database; operator inventory remains necessary.

## Proposed rollout, not executed

1. Stop every old scheduler/client/tab and backend/Companion writer that can touch
   the same accounts, DB or profiles. Record image/source identities and make
   consistent, mutually identified snapshots of the DB and Companion state. Do
   not combine a current DB with unrelated old flow or receipt files.
2. Review diagnostic evidence against the pre-stop inventory. Any blocked,
   unreadable, browser-only or identity-mismatched state is a no-go. Resolve it in
   a separately approved recovery/migration task; this candidate offers no force
   clear, TTL expiry or automatic adoption endpoint.
3. Only after a separate deployment approval, install matched backend/Companion/UI
   versions and the earlier control-table migration through its designated DB
   owner. A newer Companion refuses old protocol writes; a newer backend refuses
   an older Companion's missing capability. This does not neutralize an old
   backend binary still writing a shared DB, so stopping old writers is mandatory.
4. Keep rotation/usage-triggered automation disabled. Live HTTP/real-account
   qualification requires separate authorization and is not implied by any test
   here. The offline manual contract is the current verification ceiling.

## Rollback decision

Before new work has crossed an external-effect boundary, a coordinated code
rollback can be evaluated against the recorded compatible snapshots. Once a
membership/browser/OAuth action may have happened, rolling back DB or receipt
files alone can erase the only completion evidence while the external effect
remains. Stop new writes and preserve current evidence; do not automatically
restore old files or reopen old automation. Recovery and any rollback after that
point require a reviewed identity/receipt reconciliation plan. No rollback or
operational recovery action was executed in this change.
