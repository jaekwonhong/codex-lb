## ADDED Requirements

### Requirement: Companion account-pool mutations publish only committed state

If account-pool validation or persistence fails, the in-process account document,
revision, effective catalog and owner bindings SHALL retain their last committed
state. A later successful unrelated operation SHALL NOT silently commit the
failed operation's tentative changes.

#### Scenario: Observed identity correction cannot be persisted
- **WHEN** saving a corrected managed member identity fails
- **THEN** the operation reports failure and the prior identity and revision remain visible
- **AND** repeating the explicit correction does not falsely report it already stored

#### Scenario: Failed policy change precedes a different successful mutation
- **WHEN** a policy save fails and a later explicit account update succeeds
- **THEN** the later update does not include the failed policy value
