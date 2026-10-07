# Tasks

## 1. Freeze and discovery

- [x] 1.1 Freeze the superseded OpenCodex -> Codex-LB downstream design as a retained validation/rollback artifact and create an isolated extraction worktree from a source revision that contains the current member-management modules.
- [x] 1.2 Inventory file-level imports and runtime dependencies for `member_switch`.
- [x] 1.3 Inventory file-level imports and runtime dependencies for `member_auth_handoff`.
- [x] 1.4 Inventory file-level imports and runtime dependencies for `member_rotation_operator`.
- [x] 1.5 Classify the shared dependencies into membership-domain, persistence, account-state, data-plane/proxy, usage/quota, scheduler/runtime, and external-effect categories.

## 2. Boundary definition

- [x] 2.1 Define the minimum Workspace Member Controller responsibility set and explicit non-responsibilities.
- [x] 2.2 Record which account-pool, quota, affinity, failover, and exact-account-selection behaviors are owned by OpenCodex.
- [x] 2.3 Define the OpenCodex account identity/state projection consumed by the Controller and the workspace/member mapping contract.

## 3. Incremental extraction

- [x] 3.1 Extract workspace catalog/read models from Codex-LB proxy/account types.
- [x] 3.2 Extract membership observation behind an independent port.
- [x] 3.3 Extract the minimum workspace-intent and membership-operation persistence contract.
- [x] 3.4 Stand up a read-only Controller API for catalog/status/observation.
- [x] 3.5 Implement the OpenCodex account-state adapter.
- [x] 3.6 Extract add/remove/switch mutation commands and preserve durable no-replay recovery.
- [x] 3.7 Replace Codex-LB usage/quota inputs used by rotation decisions with OpenCodex-owned account state where the contract is sufficient.
- [x] 3.8 Remove remaining Codex-LB account/proxy/data-plane dependencies from the Controller boundary.

## 4. Qualification and cutover

- [x] 4.1 Package the standalone service with health, admin authentication, configuration, and migration/startup validation.
- [x] 4.2 Run a read-only shadow deployment and compare workspace/member results with the existing Codex-LB implementation.
- [x] 4.3 Qualify one separately authorized workspace mutation canary and rollback/recovery without broadening mutation authority.
  - [x] 4.3.1 Execute q1 and q2 forward budgets at most once each and retain authoritative no-replay evidence.
  - [x] 4.3.2 Preserve the q2 confirmed-removal + pending-invite partial effect as outcome-unknown rather than replaying or normalizing it.
  - [x] 4.3.3 Implement and mechanically qualify a purpose-bound partial-effect recovery contract with schema-4 downgrade rejection and Controller two-phase release evidence.
  - [x] 4.3.4 Deploy the exact qualified recovery candidate, pass recovery preflight, restore the original member once, and retain final restoration evidence before declaring the canary qualification complete.
- [ ] 4.4 Transfer production workspace-membership control-plane ownership to the standalone Controller.
- [ ] 4.5 Make OpenCodex the direct ChatGPT/Codex account-pool owner for PC1/PC2/Mac and retire the Codex-LB inference/data-plane path.
- [ ] 4.6 Remove superseded routing artifacts only after final rollback snapshots and operational evidence are retained.
