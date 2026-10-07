## MODIFIED Requirements

### Requirement: OpenCodex is the only active production inference data plane

After task 4.5, PC1, PC2 and Mac SHALL send ordinary ChatGPT/Codex inference
traffic directly to OpenCodex. Codex-LB Stable/Beta SHALL NOT remain an active
second production inference proxy, account-pool router or automatic fallback.
Stable/Beta MAY be retained stopped as explicit rollback artifacts until the
later cleanup task.

#### Scenario: One client has not proven OpenCodex cutover

- **GIVEN** any of PC1, PC2 or Mac lacks exact current evidence selecting the
  OpenCodex provider
- **WHEN** task 4.5 retirement readiness is evaluated
- **THEN** Stable/Beta remain available and the data-plane retirement is
  blocked
- **AND** an idle 2455/2456 connection set does not override the missing
  per-client evidence.

#### Scenario: All clients are direct and the drain is clean

- **GIVEN** PC1, PC2 and Mac all select OpenCodex, OpenCodex and WMC are ready,
  the task-4.4 writer fence is intact, and no client connection uses 2455/2456
- **WHEN** the operator retires the Codex-LB data plane
- **THEN** Stable/Beta are stopped without deleting rollback artifacts
- **AND** active 2455/2456 ingress is disabled
- **AND** OpenCodex 10101 remains the active inference ingress.

#### Scenario: Explicit rollback is required

- **GIVEN** the retained Stable/Beta rollback artifacts and saved ingress
  configuration are intact
- **WHEN** an operator deliberately rolls back an affected client
- **THEN** the exact prior Stable/Beta service and ingress are restored before
  that client selects its rollback profile
- **AND** OpenCodex does not automatically fail over requests into Codex-LB.

### Requirement: Workspace membership ownership is unchanged by inference retirement

Retiring the Codex-LB inference path SHALL NOT move workspace-membership or
inference-account authority across the task-4.4 boundary. WMC SHALL remain the
production membership writer and OpenCodex SHALL remain the inference-account
credential/routing authority.

#### Scenario: Data-plane retirement completes

- **WHEN** Stable/Beta inference is stopped after task-4.5 qualification
- **THEN** WMC remains mutation-enabled and ready with its existing durable
  membership journal
- **AND** the q2 historical mutation/recovery is not replayed
- **AND** no Codex-LB legacy membership writer is re-enabled.
