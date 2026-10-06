## ADDED Requirements

### Requirement: Workspace membership control is separated from the inference data plane

The system SHALL provide workspace membership management through a standalone Workspace Member Controller control-plane boundary. Ordinary model requests SHALL route directly through OpenCodex and SHALL NOT traverse the Controller. OpenCodex SHALL remain the authority for ChatGPT/Codex account-pool selection, quota/cooldown state, request failover, and thread/account affinity. The Controller SHALL consume only the account-state projection needed for workspace membership decisions and SHALL NOT maintain an independent inference-routing authority.

#### Scenario: Ordinary inference bypasses the Controller

- **GIVEN** PC1, PC2, or Mac sends an ordinary model request
- **WHEN** OpenCodex routes the request to ChatGPT/Codex or another configured provider
- **THEN** the request is served without traversing the Workspace Member Controller
- **AND** Controller availability does not become an inference-path dependency

#### Scenario: Workspace membership operation uses account state without owning routing

- **GIVEN** a workspace membership decision requires the identity or current state of a ChatGPT/Codex account
- **WHEN** the Workspace Member Controller evaluates that decision
- **THEN** it consumes the defined OpenCodex account-state projection for the exact account identity
- **AND** it does not independently select an inference account, calculate request failover, or establish thread affinity

#### Scenario: Controller outage does not create a second data-plane fallback

- **GIVEN** the Workspace Member Controller is unavailable
- **WHEN** OpenCodex receives an otherwise valid model request
- **THEN** OpenCodex continues to apply its own configured account-pool and provider-routing behavior
- **AND** the system does not fall back to Codex-LB as a second inference router merely because the Controller is unavailable
