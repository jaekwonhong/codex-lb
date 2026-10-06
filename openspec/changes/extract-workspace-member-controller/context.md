# Context

## Target architecture

```text
PC1 / PC2 / Mac
       |
       v
    OpenCodex
       |-- ChatGPT / Codex account pool
       |-- GLM5.3 -> DGX Spark + MSI edgeXpert
       |-- Anthropic
       |-- Gemini
       `-- OpenRouter / other providers

Workspace Member Controller
       |-- workspace catalog
       |-- owner/member observation
       |-- workspace intent
       |-- member add/remove/switch
       `-- durable membership-operation recovery

OpenCodex account state <----> Workspace/member identity contract
```

OpenCodex is the data plane. The Workspace Member Controller is a control plane and MUST NOT become a hop in ordinary inference traffic.

## Ownership principle

OpenCodex should own request-facing ChatGPT/Codex account state: selectable accounts, quota/cooldown, routing/failover, thread/account affinity, and exact account selection. The Controller should own workspace membership facts and effects: workspace identity, owner/member observation, intended membership, membership mutation, and the durable evidence needed to avoid unsafe replay.

The Controller must consume the minimum account-state projection needed for membership decisions. It must not become a second source of truth for account quota or request routing.

## Frozen ownership boundary

The detailed single-writer boundary is frozen in `ownership-contract.md`. In short:

- OpenCodex owns ChatGPT/Codex inference credentials, pool eligibility/selection, live quota/cooldown/health, exact account selection, retry/failover and thread affinity.
- Workspace Member Controller owns workspace catalog/observation/intent, membership effects, membership-specific mutation limits, durable effect/no-replay recovery and membership decision evidence.
- Account-pool rotation and workspace-member rotation are distinct authorities. The Controller may consume or command OpenCodex through a defined adapter, but never becomes a second writer of account routing/quota/credential state.
- Existing `member_auth_handoff` account/routing mutations and `rotation_worker` account/usage/reset orchestration are extraction seams, not capabilities that move unchanged.

## Frozen account identity/state contract

The cross-service identity and freshness boundary is frozen in `account-identity-state-contract.md`. The durable foreign identity is the exact OpenCodex `account_id`; selectors, aliases, log labels and emails are never sufficient join keys. Credential/main identity generations and an opaque state revision fence decisions and commands but do not form durable workspace-member identity. Required account evidence is exact-account, freshness-bounded and fail-closed.

## Extracted workspace read boundary

Slice 4 introduces `app.modules.workspace_member_controller` as the dependency-light Controller domain/read boundary. Workspace catalog, member/owner read models, membership observations, and the read-only catalog/observation Protocols live there without importing Codex-LB dashboard, proxy, account, database-model, or dependency-container modules. The legacy `member_switch.schemas` module re-exports those models so existing routes and tests retain the same wire contract while runtime callers migrate toward the standalone boundary.

## Minimal persistence and read-only API boundary

Slice 5 adds a dependency-light persistence contract for Controller-owned workspace intent and membership-operation journal state plus a standalone read service/API skeleton. The Controller core does not import ORM models. Existing durable `MemberRotationWorkspaceControl` and `MemberSwitchControlRecord` rows are reused only through `legacy_persistence.py` compatibility adapters so migration does not create duplicate state authorities. The read API exposes only `GET /v1/catalog`, `GET /v1/status`, and `GET /v1/workspaces/{workspace_id}/observation`; it does not expose mutation methods, raw journal payloads, command hashes, account credentials, or Codex-LB dashboard authentication. Service authentication remains a packaging concern for slice 9.

Membership observation remains a live read-port concern in this slice rather than a newly persisted mirror. Durable observation/evidence is added only when a later mutation workflow explicitly needs immutable operation evidence.

## OpenCodex exact-account state adapter

Slice 6 adds a narrow OpenCodex management-plane projection at `GET /api/codex-auth/controller-account-state?accountId=...` and a Controller HTTP adapter for it. The qualified OpenCodex source checkpoint is `af4f476` (`feature/controller-account-state-projection-20261006`). The OpenCodex route requires the raw management `admin-token` principal, accepts exactly one account id, returns only normalized non-secret account state, and reads current OpenCodex config/credential-generation/runtime-health/quota caches without probing upstream or inspecting other accounts. A cold/unobserved quota therefore remains `unknown` and is rejected later by Controller freshness/admission policy rather than refreshed implicitly.

The projection includes exact account id, pool credential generation or main identity generation, observation time, normalized health/selection/quota state, optional quota windows/reset-credit evidence, current cooldown evidence, and a deterministic SHA-256 `stateRevision` over the stable normalized state. `observedAt` is intentionally excluded from that digest so identical state has the same revision across repeated reads. No access token, refresh token, cookie, upstream bearer, ChatGPT physical account id, or raw upstream response is returned.

The Controller-side adapter uses `Authorization: Bearer <OpenCodex admin token>`, verifies the returned account id exactly, validates the projection schema/generation namespace, maps 404/auth/unavailable failures into explicit fail-closed errors, and exposes freshness helpers without independently recalculating OpenCodex selection eligibility. Rotation/mutation code is not wired to this adapter in this slice.

## Durable membership mutation command boundary

Slice 7 extracts add/remove/switch commands into the standalone Controller core without exposing a mutation HTTP route yet. `WorkspaceMembershipMutationAdmission` revalidates the exact catalog fingerprint, workspace id/account id, configured incoming identity, and a complete owner-verified non-ambiguous membership observation immediately before a new effect claim. The observation must be no more than 30 seconds old by default; outgoing removal/switch identity must be present exactly in that observation and the workspace owner cannot be used as an incoming membership target.

`WorkspaceMembershipMutationService` writes a Controller-owned typed operation into the existing durable member-switch CAS journal through `MembershipMutationJournal`. The legacy table remains the single mutable authority during migration: `LegacyMembershipMutationJournal` stores rows as `controller_membership_mutation` and reuses the existing command-receipt uniqueness/CAS semantics. A command claim containing operation id, command id, action and canonical SHA-256 request fingerprint is committed before `MembershipMutationEffectPort.execute` may run. The claimed state is then durably marked `effect_pending` before the external effect call.

A lost/ambiguous effect response leaves the command pending indefinitely. Re-submitting the same command id/fingerprint returns the existing unknown state and never calls `execute` again. Recovery calls only `MembershipMutationEffectPort.reconcile` with the original operation id, command id and request fingerprint; a missing receipt remains `outcome_unknown`. A receipt must echo the exact operation, command, fingerprint, action and workspace identity. Completed receipts require action-appropriate confirmed add/remove effect evidence plus final membership confirmation; authoritative non-effect receipts may terminate safely only when they contain no confirmed/unknown effect evidence.

The legacy `member_switch` admission path recognizes this new journal kind so an active/pending Controller mutation blocks competing work, while a valid terminal `completed` or `failed` Controller record with released scope is inert history rather than a permanent `unknown_control_record` blocker. Core mutation modules remain free of Codex-LB ORM, proxy, account, handoff, rotation-operator, dashboard and dependency-container imports; only the migration adapter imports the legacy journal.

No production membership effect adapter or mutation network endpoint is activated in this slice. Those remain behind standalone service authentication/packaging and the separately authorized mutation canary.

## OpenCodex-owned rotation decision boundary

Slice 8 replaces the extracted Controller rotation decision inputs with exact OpenCodex account state. `WorkspaceMemberRotationDecisionService` first proves the current workspace/member identity from the Controller catalog and a fresh authoritative membership observation, then resolves only the durable `WorkspaceMemberAccountBinding.opencodex_account_id`; it never joins an inference account by email, selector, alias, or Codex-LB `Account` row. The decision reads that exact account through `OpenCodexAccountStatePort` and uses OpenCodex's normalized `quotaState`, selection/exclusion state, reset-credit count, freshness timestamps, credential/main generation and state revision. Raw quota percentages are retained only as immutable evidence and are never reinterpreted to decide exhaustion.

A fresh normalized `quotaState=available` ends the evaluation without membership rotation. Unknown/stale quota, unavailable/missing credential state, reauth/pause, unknown selection state, unexpected exclusion reasons, missing durable account binding, or missing reset-credit evidence fail closed. `quotaState=exhausted` is not itself sufficient: the projected state must remain generation-fenced, the OpenCodex reset-credit count must be known, and an available reset credit returns `reset_required` without reserving a membership mutation. This slice intentionally does not call the legacy Codex-LB reset-credit executor; a future production reset action must use an OpenCodex-owned fenced/idempotent management command. An exhausted account with a fresh authoritative reset-credit count of zero may proceed to the Controller-owned rolling membership-mutation budget.

The existing `MemberRotationQuotaOperation` rolling 24h/168h policy remains Controller-owned membership safety state, not inference quota. `LegacyMembershipMutationBudget` is a migration adapter that exposes it through the data-plane-independent `MembershipMutationBudgetPort`; it accepts only workspace/evaluation/operation identity and no Codex-LB account or usage object. The old `member_switch.rotation_worker`, Codex-LB `AccountsRepository`, background usage updater, weekly-usage fetch types, and Codex-LB reset executor remain legacy compatibility code outside the extracted Controller core and are not imported by it.

An admitted rotation decision emits immutable `AccountDecisionEvidence` containing the exact OpenCodex account id, applicable generation, state revision, capture/quota times and normalized decision state. Automatic membership commands may embed that evidence in the durable mutation journal. After the mutation command has been durably claimed and marked effect-pending, `WorkspaceMembershipMutationService` revalidates the exact OpenCodex evidence immediately before calling the external membership effect. If generation, state revision, exhausted/no-reset-credit preconditions, freshness, or account availability changed, the Controller records an authoritative local non-effect receipt and releases the mutation scope without calling the membership effect.

All non-legacy modules under `app.modules.workspace_member_controller` are regression-checked against imports from Codex-LB DB/account/proxy/usage/reset/member-switch/data-plane modules. The only remaining imports of those implementations live in explicitly named `legacy_*` migration adapters. Production ownership still changes only in the later shadow/canary/cutover slices.

## Standalone Controller process packaging

Slice 9 packages the extracted control-plane core as a dedicated `workspace-member-controller` process without starting Codex-LB's proxy, dashboard, account pool, usage schedulers or request handlers. The process owns a minimal FastAPI/uvicorn shell, reads only `WMC_` configuration, listens on loopback by contract in this qualification stage, disables interactive API documentation, exposes public liveness/readiness probes, and protects every `/v1` Controller read route with a dedicated bearer admin token. No membership mutation HTTP route is activated.

Secrets are supplied either directly through environment values or through absolute owner-only token files; a secret cannot have both sources and token-file modes with group/world permissions are rejected. The OpenCodex management base may use plaintext HTTP only for loopback/localhost/`host.docker.internal`. The migration database URL is explicit and durable; in-memory SQLite and relative SQLite paths are rejected. `workspace-member-controller --validate` performs the same dependency/startup qualification without opening a listener.

The standalone process no longer imports `app.main`, `app.db.session`, `app.dependencies`, dashboard auth, account repositories, proxy code, usage schedulers or Codex-LB process configuration. During migration it reads the existing Controller-owned tables through direct SQL read adapters and validates both required table names and the columns relied on by the extracted contracts. The later mutation canary still owns qualification of write adapters.

Workspace observation is provided by a read-only Companion HTTP adapter that preserves the qualified local Host/Origin/control-protocol contract and the existing 190-second interactive observation timeout. OpenCodex startup readiness uses exact unauthenticated `/readyz`; therefore a read-only shadow deployment with an empty binding file still proves OpenCodex is ready. When bindings exist, startup additionally reads every exact referenced account through the non-secret Controller account-state projection.

Member-to-account bindings are supplied only by an explicit versioned JSON file. Startup verifies each row against the exact current Companion workspace/member identity and then against the exact OpenCodex account id. The file rejects duplicate workspace-member identities and reuse of one OpenCodex account by conflicting subjects. Empty bindings are permitted for read-only shadow qualification, but no account-dependent mutation may infer a missing binding from email, selector, alias or former Codex-LB account identity.

## Extraction strategy

The current member-management implementation is not treated as a cleanly separable package. It still imports Codex-LB database models, account repositories, OAuth/auth-handoff services, proxy account cache, usage observations, reset-credit facilities, and scheduler/runtime support. Those dependencies will be inventoried before an extraction boundary is finalized.

Extraction therefore proceeds by preserving behavior behind explicit ports and replacing data-plane dependencies one at a time. No wholesale copy of the existing modules into a new service is considered complete merely because it imports successfully.

## Safety boundary

Existing owner/identity verification, membership observation, freshness/admission checks, durable operation ownership, and no-replay behavior remain safety requirements during the extraction. Any dependency that currently carries one of those guarantees must be identified before it is removed or replaced.

Production membership ownership changes only after a read-only shadow comparison and a separately authorized single-workspace mutation canary with rollback evidence.

## Non-goals for the extraction

- Reimplement OpenCodex account-pool routing inside the Controller.
- Keep Codex-LB as a second inference proxy after the extraction is complete.
- Move GLM/Anthropic/Gemini/OpenRouter routing into the Controller.
- Infer undocumented workspace churn limits or relax existing membership-effect safety gates.
- Change production membership or account credentials during the dependency-inventory and boundary-definition stages.
