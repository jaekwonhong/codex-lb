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
