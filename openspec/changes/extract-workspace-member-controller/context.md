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
