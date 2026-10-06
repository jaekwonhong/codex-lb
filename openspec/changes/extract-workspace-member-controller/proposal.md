# Extract workspace member control from the Codex-LB data plane

## Why

The long-term serving architecture makes OpenCodex the single client ingress and the owner of ChatGPT/Codex account-pool routing, quota state, affinity, and failover. Keeping Codex-LB in the inference request path only to retain workspace-member operations would preserve a second proxy/routing plane and duplicate account state.

Codex-LB already contains distinct workspace-member capabilities (`member_switch`, `member_auth_handoff`, and `member_rotation_operator`) that can become a separate control-plane service. The extraction must preserve the conservative membership safety model while removing dependencies that exist only because those capabilities currently live inside Codex-LB.

## What Changes

- Introduce a standalone Workspace Member Controller boundary for workspace catalog, owner/member observation, workspace intent, membership mutation, and durable membership-operation recovery.
- Move ChatGPT/Codex credential lifecycle, account-pool selection, quota/cooldown interpretation, exact account selection, thread/account affinity, retry, and failover ownership to OpenCodex rather than reimplementing those behaviors in the Controller.
- Define an explicit identity/state contract between OpenCodex account records and workspace/member identities so the Controller can consume account state without owning request routing or account credentials.
- Extract the existing member-management behavior incrementally behind ports/adapters before any production ownership changes.
- Qualify the extracted service read-only first, then a single-workspace mutation canary, before retiring the Codex-LB data plane.

## Capabilities

### New Capabilities

- `workspace-member-controller`: Standalone control-plane ownership for workspace membership observation and mutation, consuming account state from OpenCodex without joining the inference request path.

### Modified Capabilities

- `member-switch-commands`: Preserve the existing fail-closed membership command and recovery guarantees while moving their runtime ownership out of the Codex-LB data plane.
- `account-routing`: Make OpenCodex the long-term owner of ChatGPT/Codex account-pool routing so workspace membership control does not maintain an independent routing/quota authority.

## Impact

- Initial impact is architectural/specification only; no production routing, database row, account credential, workspace membership, or external mutation is changed by the proposal itself.
- Expected source areas: `app/modules/member_switch`, `app/modules/member_auth_handoff`, `app/modules/member_rotation_operator`, their persistence models, and adapters currently coupled to Codex-LB account/proxy/usage services.
- OpenCodex becomes the account-state and data-plane authority; the extracted Controller remains outside the inference request path.
- Deployment is staged: dependency inventory -> boundary extraction -> read-only shadow -> single-workspace canary -> production control-plane cutover -> Codex-LB data-plane retirement.
