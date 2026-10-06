# Workspace Member Controller dependency map

Status: frozen discovery inventory for extraction slice 1. This document is descriptive, not yet the final ownership contract.

## Inventory scope

The current source contains 32 Python files across the three member-management modules:

- `app/modules/member_switch`: 17 files
- `app/modules/member_auth_handoff`: 9 files
- `app/modules/member_rotation_operator`: 6 files

The inventory classifies dependencies into these extraction categories:

1. **membership-domain** — schemas, policy, workflow state, operation/no-replay semantics.
2. **membership-persistence** — member-switch control rows, workspace intent, rotation quota/effect journal, retained member usage snapshots.
3. **account-state/data-plane** — Codex-LB account rows/status, account routing caches, API-key cache, account selection/probe services.
4. **usage/quota/reset** — weekly usage observation, usage history/updater, reset-credit resolution, quota admission/history.
5. **credential/OAuth** — account credential handoff, device OAuth, post-OAuth account probing.
6. **scheduler/runtime** — settings, leader election, canary plan, host runtime attestation, worker orchestration.
7. **external membership effect** — Companion observation, member operation start/status/finalize, owner-side OAuth browser operations.
8. **dashboard/API shell** — FastAPI routes, dashboard permissions/errors and dependency wiring.

## High-coupling cut points

The following files are the primary data-plane coupling seams and must not be copied unchanged into a standalone Controller:

| File | Direct coupling | Why it is a cut point |
| --- | --- | --- |
| `member_auth_handoff/service.py` | `Account`, `AccountStatus`, `UsageHistory`, `get_api_key_cache`, proxy account-selection cache, routing-unavailable publication, OAuth service | Owns Codex-LB account status/credential transitions and mutates routing-visible state. This must be split behind an account-state/credential port before extraction. |
| `member_switch/rotation_worker.py` | `AccountsRepository`, `SessionLocal`, background usage updater, reset-credit resolver, quota repository, Controller dependency factory | Directly discovers Codex-LB accounts and orchestrates usage/reset/quota work. Long-term account/quota input must be replaced rather than retained. |
| `member_switch/post_probe.py` | `AccountsService`, `run_account_force_probe`, refresh errors | Performs Codex-LB-specific account probing after auth enrollment. Requires an adapter or retirement depending on the OpenCodex account-health contract. |
| `member_auth_handoff/rotation_events.py` | `Account`, `AccountStatus`, `MemberRotationQuotaOperation`, settings | Derives rotation events from Codex-LB account status transitions; must be re-bound to external account-state events/projections. |
| `member_switch/rotation_foundation.py` | weekly usage observation, reset-credit resolution, rotation quota repository | Mostly pure decision logic, but its input DTOs are Codex-LB usage/reset types. Candidate to preserve after port/type replacement. |

## `member_switch` file map

| File | Role | External/Codex-LB dependencies | Preliminary extraction posture |
| --- | --- | --- | --- |
| `__init__.py` | package marker | none | **portable** |
| `schemas.py` | workspace/member/run/operation DTOs and protocol constants | `DashboardModel` | **portable after base-model decoupling** |
| `policy.py` | identity/membership confirmation and allowed-action rules | local schemas/repository exception only | **preserve** |
| `participants.py` | participant receipt fingerprint/acceptance | local control record/schemas | **preserve** |
| `repository.py` | durable run/control/command receipt store | `Account`, `MemberSwitchCommandReceipt`, `MemberSwitchControlRecord`, SQLAlchemy | **split**: preserve control persistence; remove account quarantine lookup from core repository |
| `admission.py` | local no-new-work/admission checks | handoff durable state, controls, canary plan | **preserve after persistence ports** |
| `companion.py` | Companion HTTP client/port | `aiohttp`; external Companion endpoints | **preserve as external-effect adapter** |
| `service.py` | manual member-switch orchestration, catalog refresh/observation | `CompanionPort`, auth-handoff port, controls | **preserve as core application service after port cleanup** |
| `auth_enrollment.py` | member/owner OAuth enrollment workflow | auth-handoff port, Companion OAuth browser/profile operations, controls | **split**: workflow may stay; account credential realization moves behind external account/credential port |
| `post_probe.py` | post-OAuth account health probe | Codex-LB `AccountsService`, account probe/refresh | **replace adapter or retire** |
| `rotation_foundation.py` | pure rotation admission/read model + retained-usage input construction | Codex-LB weekly usage/reset-credit/quota DTOs | **preserve logic; replace input contracts** |
| `rotation_controller.py` | durable single-evaluation rotation controller | quota/snapshot repos, runtime attestation, member-switch service | **preserve after input/repository ports** |
| `rotation_plan.py` | canary plan model/loader | Codex-LB usage identity type | **preserve after identity type replacement** |
| `rotation_scheduler.py` | server scheduler loop | global settings, leader election, rotation worker | **replace runtime shell** |
| `rotation_worker.py` | production rotation orchestration | `AccountsRepository`, `SessionLocal`, usage updater, reset-credit resolver, app dependency factory | **rewrite around OpenCodex account-state adapter** |
| `runtime_attestation.py` | signed Companion runtime evidence verification | cryptography + local schema | **preserve** |
| `api.py` | dashboard/member-switch HTTP surface | dashboard auth/dependency container/FastAPI | **replace API shell; preserve service contracts** |

### `member_switch` external effect paths

`CompanionClient` is the only direct network boundary in this module for workspace/member effects. Its observable outbound surfaces are:

- workspace membership observation: `/workspaces/{workspace_id}/observe`
- owner/member OAuth browser/profile operations
- manual operation start: `/operations`
- canary operation start: `/canary-operations`
- operation status: `/operations/{operation_id}`
- operation finalize: `/operations/{operation_id}/finalize`

These calls are membership-control effects/observations, not inference data-plane traffic, so the adapter is structurally compatible with a standalone Controller.

## `member_auth_handoff` file map

| File | Role | External/Codex-LB dependencies | Preliminary extraction posture |
| --- | --- | --- | --- |
| `__init__.py` | package marker | none | **portable** |
| `schemas.py` | handoff/auth observation/usage DTOs | `DashboardModel` | **portable after base-model decoupling** |
| `repository.py` | custom member-auth catalog overlay | file/temp/RLock + `DashboardModel` | **portable with config/storage cleanup** |
| `catalog.py` | packaged + overlay member/account catalog | local repository/schemas | **preserve initially; later bind identities to OpenCodex account contract** |
| `durable.py` | durable handoff envelope/store integration | member-switch control repository | **preserve after generic journal port** |
| `usage_snapshot_repository.py` | immutable removed-member usage snapshots/reset invalidation | DB models + SQLAlchemy + sqlite writer guard | **preserve persistence semantics; move schema ownership** |
| `rotation_events.py` | quota event observation/claim/settle and rolling quota repository | `Account`, `AccountStatus`, rotation quota DB row, settings | **split**: keep durable quota/effect ledger; replace Codex-LB account-status event source |
| `service.py` | credential handoff/reconciliation and workspace auth observation | `Account`, `AccountStatus`, `UsageHistory`, OAuth service, API-key cache, proxy account cache/routing publication | **major split**: membership identity/handoff policy vs Codex-LB account credential/routing mutation |
| `api.py` | dashboard handoff/usage/observation endpoints | dashboard auth/dependencies/FastAPI | **replace API shell; preserve domain contracts as needed** |

## `member_rotation_operator` file map

| File | Role | External/Codex-LB dependencies | Preliminary extraction posture |
| --- | --- | --- | --- |
| `__init__.py` | package marker | none | **portable** |
| `schemas.py` | operator read-model DTOs | `DashboardModel` | **portable after base-model decoupling** |
| `repository.py` | workspace intent + unresolved quota/effect lookup | `MemberRotationWorkspaceControl`, `MemberRotationQuotaOperation`, SQLAlchemy | **preserve persistence semantics** |
| `adapter.py` | builds operator snapshot from durable controller/quota/usage state | DB session/models + member-switch controller/snapshots | **preserve read-model role after repository ports** |
| `service.py` | aggregates catalog, usage, quota, controller and intent into operator view | settings + auth catalog/overlay + snapshot/quota repositories | **preserve after config/account catalog ports** |
| `api.py` | read operator status + update workspace intent | dashboard auth/FastAPI/get_session | **replace API shell** |

## Database/model coupling inventory

Current direct DB model ownership crossing the extraction boundary:

| Model | Current users in member modules | Category |
| --- | --- | --- |
| `MemberSwitchControlRecord` | member-switch repository; rotation operator adapter | membership-persistence |
| `MemberSwitchCommandReceipt` | member-switch repository | membership-persistence |
| `MemberRotationWorkspaceControl` | rotation operator repository | membership-persistence |
| `MemberRotationQuotaOperation` | rotation operator repository/adapter; auth-handoff rotation events | membership-persistence / quota-effect ledger |
| `WorkspaceMemberFinalUsageSnapshot` | usage snapshot repository | membership history |
| `WorkspaceMemberUsageResetInvalidation` | usage snapshot repository | membership history |
| `Account` | member-switch repository/rotation worker; auth-handoff service/rotation events | **account-state/data-plane coupling** |
| `AccountStatus` | auth-handoff service/rotation events | **account-state/data-plane coupling** |
| `UsageHistory` | auth-handoff service | **usage/account-state coupling** |

The first six are candidates to move with the Controller's persistence boundary. `Account`, `AccountStatus`, and `UsageHistory` are not Controller-owned by default; they mark the seam that must be replaced by an OpenCodex-facing account-state/identity contract or another explicitly retained credential service.

## Non-DB hard couplings

### Account/routing state

- `member_auth_handoff/service.py`
  - `get_account_selection_cache().invalidate()`
  - `mark_account_routing_unavailable(...)`
  - `propagate_account_routing_change()`
  - `get_api_key_cache().clear()`
- `member_switch/post_probe.py`
  - `AccountsService`
  - `run_account_force_probe(...)`
- `member_switch/rotation_worker.py`
  - `AccountsRepository(...).list_accounts()`

These are Codex-LB data-plane/account-runtime semantics and cannot remain in the final standalone membership Controller unchanged.

### Usage/quota/reset

- `app.core.usage.weekly_observation`
- `app.modules.usage.updater`
- `app.modules.rate_limit_reset_credits.rotation_resolution` (`resolve_rotation_reset_credit`, `build_rotation_usage_refresh_callback`)
- `member_auth_handoff.rotation_events.RotationQuotaRepository`
- `member_auth_handoff.usage_snapshot_repository.MemberUsageSnapshotRepository`

The durable membership-effect quota/history pieces are separable from the source of live account usage/quota. Live account quota/health input is a replacement seam; immutable member-removal history and no-replay/effect accounting remain Controller concerns until the ownership contract says otherwise.

### Scheduler/runtime

- `get_settings()` in scheduler/worker/operator/rotation-events
- `get_leader_election()` in rotation scheduler
- file canary plan + signed runtime attestation
- global `app.dependencies` factories

These belong to the current Codex-LB process shell and need standalone-service equivalents rather than domain reuse by import.

### Dashboard/API shell

All three `api.py` files bind to Codex-LB dashboard permission/session/error dependencies. Those routes are not portable as-is; the domain/application services beneath them are the extraction targets.

## Dependency direction summary

```text
Dashboard/API shell
       |
       v
member_switch service/auth/controller  ---> Companion external effects
       |          |                         (observe/add/remove/invite/OAuth)
       |          +----> durable membership journals/snapshots/intent
       |
       +----> member_auth_handoff service
                  |
                  +----> Codex-LB Account / AccountStatus / UsageHistory
                  +----> OAuth service
                  +----> proxy account-selection cache / API-key cache

rotation scheduler/worker
       |
       +----> AccountsRepository + usage updater + reset-credit resolver
       +----> rotation foundation/controller
       +----> membership-effect quota/history

member_rotation_operator
       +----> catalog + durable controller/quota/history + workspace intent
```

## Extraction risk classification

### Low-coupling / preserve-first candidates

- `member_switch/policy.py`
- `member_switch/participants.py`
- `member_switch/runtime_attestation.py`
- most schema/read-model definitions after removing `DashboardModel`
- core portions of `member_switch/service.py`
- core portions of `member_switch/rotation_controller.py`
- durable membership journal/history semantics
- `member_rotation_operator` aggregation semantics
- Companion effect adapter contract

### Adapter/split required

- `member_switch/repository.py`
- `member_switch/auth_enrollment.py`
- `member_switch/rotation_foundation.py`
- `member_switch/rotation_plan.py`
- `member_auth_handoff/catalog.py`
- `member_auth_handoff/durable.py`
- `member_auth_handoff/rotation_events.py`
- `member_auth_handoff/usage_snapshot_repository.py`
- rotation operator repository/adapter/service

### Rewrite/retire candidates because they encode Codex-LB data-plane ownership

- `member_auth_handoff/service.py` account/routing mutation portions
- `member_switch/rotation_worker.py`
- `member_switch/post_probe.py`
- Codex-LB `api.py`/dependency-container bindings
- Codex-LB scheduler/settings/leader-election shell

## Slice-1 conclusion

The member-management capability is separable, but not by moving the three module directories intact. The durable membership workflow, effect/no-replay safety, observation and operator read models form a coherent control-plane core. The strongest coupling to the inference data plane is concentrated in account credential/status mutation, account routing-cache publication, account probing, live usage refresh/reset-credit orchestration, and the Codex-LB process shell. Those seams are the inputs to the next ownership-boundary slice.
