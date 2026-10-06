# OpenCodex / Workspace Member Controller ownership contract

Status: normative architecture boundary for extraction slice 2. Identity field shapes and transport APIs are intentionally deferred to the next slice.

## Single-writer ownership table

| Concern | OpenCodex | Workspace Member Controller |
| --- | --- | --- |
| Model/provider routing | **Owner** | Never |
| ChatGPT/Codex credential storage, login, reauth, refresh | **Owner** | Never stores or refreshes inference-account credentials |
| ChatGPT/Codex pool membership and selectable-account set | **Owner** | References accounts only through the later identity contract |
| Pool selection strategy and account priority | **Owner** | Never selects an inference account |
| Thread/account affinity and sticky routing | **Owner** | Never establishes or repairs request affinity |
| Request retry/failover/cooldown | **Owner** | Never retries an inference request or maintains routing cooldown |
| Live account quota/usage observation | **Owner** | Read-only consumer of the minimum projection required for membership policy |
| Account quota reset-credit/grant state and execution | **Owner** | May request an explicit OpenCodex-owned operation later; never implements a second reset authority |
| Exact account selector / account namespace | **Owner** | May retain the foreign reference required to address an exact account |
| Workspace catalog and workspace identity | Never | **Owner** |
| Workspace owner/member observation | Never | **Owner** |
| Desired workspace membership / operator intent | Never | **Owner** |
| Member add/remove/switch/invite/join workflow | Never | **Owner** |
| Membership-specific rolling mutation limits | Never | **Owner** |
| Membership operation journal, unknown-effect state and no-replay recovery | Never | **Owner** |
| Membership-specific canary budget and effect admission | Never | **Owner** |
| Companion membership-effect adapter and runtime attestation | Never | **Owner** |
| Immutable evidence retained for a membership decision | Source of live account evidence | **Owner of the audit snapshot**, but the snapshot is never live quota authority |

## OpenCodex ownership

OpenCodex is the only request-facing authority for ChatGPT/Codex accounts. The Controller MUST NOT recreate or mirror the mechanisms below as independent mutable state:

- account credential persistence, token refresh, login and reauthentication;
- account-pool eligibility, pause/resume, priority and selection strategy;
- quota/cooldown/health evidence used by request routing;
- proactive or failure-driven account switching;
- request retry/failover and thread/account affinity;
- exact account selection through account namespaces/selectors;
- account-level quota reset-credit/grant state and execution;
- inference request accounting needed to operate those mechanisms.

Current OpenCodex source evidence for this boundary includes Pool mode for the canonical OpenAI provider, per-account quota refresh, pool strategy/sticky controls, exact `selector/model` routing that fails closed, account cooldown/pause/reauth state, and quota reset-credit services. The Controller contract depends on the capability boundary, not on the current CLI command names.

## Workspace Member Controller ownership

The Controller is the single authority for workspace membership control-plane state and effects:

- workspace catalog, workspace identity and display metadata;
- workspace owner and current-member observation;
- desired membership / enabled rotation intent;
- membership-specific candidate and policy decisions;
- add/remove/switch/invite/join orchestration through the qualified membership-effect adapter;
- durable effect ownership, operation receipts, unknown-effect handling and no-replay recovery;
- membership-specific rolling replacement limits and canary effect budget;
- immutable membership-decision evidence and removed-member historical snapshots required for audit/recovery;
- host/runtime attestation required before a membership mutation.

The Controller MAY use an OpenCodex account-state projection as decision evidence. It MUST fail closed when required account evidence is missing, stale, ambiguous, or refers to a different account generation/identity under the later account-state contract.

## Credential boundary

Inference-account credentials belong to OpenCodex. The extracted Controller MUST NOT persist ChatGPT/Codex access tokens, refresh tokens, API keys used for inference routing, or a second mutable copy of OpenCodex account status.

Existing `member_auth_handoff` behavior therefore does not move wholesale. Its membership identity/reconciliation semantics may survive, but any part that writes `Account`/`AccountStatus`, refreshes inference credentials, invalidates Codex-LB account/API-key caches, or publishes routing changes must be replaced by an OpenCodex-owned account-management boundary or retired.

This does not move the qualified Companion's workspace-admin browser/session capability into OpenCodex. Credentials/session state needed solely to observe or mutate workspace membership remain part of the membership-effect boundary and are not inference-account routing credentials.

## Quota and rotation boundary

Two different rotations exist and MUST NOT share authority:

1. **Account-pool rotation** chooses which ChatGPT/Codex account serves an inference request. OpenCodex owns it.
2. **Workspace-member rotation** changes who belongs to a ChatGPT workspace. The Controller owns it.

The Controller may decide that a workspace member is eligible for replacement based partly on OpenCodex-provided account evidence. It may persist the exact evidence used for that decision so a later audit can explain the effect. Such a snapshot is immutable decision evidence only; it MUST NOT be refreshed independently into a competing quota database or used as current routing state.

If membership policy requires an account-level reset-credit/grant operation before replacement, the Controller MUST call an OpenCodex-owned command boundary and bind the returned receipt/evidence to the membership evaluation. It MUST NOT reuse or recreate Codex-LB's reset-credit executor as a second authority.

## Cross-boundary commands

A membership transition may require a corresponding account lifecycle action, such as making a removed workspace account unavailable to future inference. In that case:

- the Controller MAY request an account-management command through the OpenCodex adapter;
- OpenCodex remains the writer of account eligibility/status/credential state;
- the Controller records only the command identity/receipt needed for its membership workflow;
- unknown command outcome fails closed and is reconciled by reading OpenCodex state rather than directly writing it;
- membership effect replay authority is never inferred from an OpenCodex account-state write.

The concrete commands and idempotency fields are deferred to the account identity/state contract slice.

## Explicitly forbidden duplicate authorities

The final Controller MUST NOT contain or depend on equivalents of:

- Codex-LB `AccountsRepository` for request-account selection;
- Codex-LB proxy account-selection cache;
- Codex-LB API-key cache invalidation for inference routing;
- a Controller-owned account cooldown or routing-health database;
- a Controller-owned live account quota refresher used as an authority parallel to OpenCodex;
- Codex-LB thread/session affinity or request retry/failover code;
- a second ChatGPT/Codex credential refresh/login store.

Temporary compatibility adapters may exist during migration, but shadow/canary qualification MUST identify them explicitly and production cutover MUST remove them from the final ownership boundary.

## Failure isolation

- Controller outage blocks only membership-control operations that require the Controller; it does not alter OpenCodex inference routing.
- OpenCodex account-state outage or stale evidence blocks Controller decisions that require that evidence; it does not authorize the Controller to use a stale mirror as current truth.
- Membership-effect ambiguity remains in the Controller's durable journal and never grants inference account failover authority.
- Inference account failure/cooldown remains in OpenCodex and never grants membership mutation authority by itself.
