## ADDED Requirements

### Requirement: Background token rotation preserves the repository port contract

Background token rotation SHALL accept and forward the existing optional routing
policy override to the canonical token repository. It SHALL preserve ciphertext
compare-and-set and the operator's preserve policy.

#### Scenario: Workspace policy accompanies refreshed credentials
- **WHEN** a background refresh obtains credentials and a known workspace routing policy
- **THEN** the same guarded repository write persists both
- **AND** no missing-argument failure discards the refreshed credentials

#### Scenario: Another writer already rotated credentials
- **WHEN** the expected refresh ciphertext no longer matches
- **THEN** the background write changes neither credentials nor routing policy
