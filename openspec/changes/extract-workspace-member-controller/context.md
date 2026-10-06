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
