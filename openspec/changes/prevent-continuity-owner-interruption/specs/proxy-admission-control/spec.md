## ADDED Requirements

### Requirement: New-work admission respects applicable fresh quota pressure

Before new-work admission, the proxy MUST consider applicable fresh usage evidence
and existing in-flight reservation pressure. An elapsed default rate-limit hold
MUST NOT erase still-current exhaustion evidence. Model-specific quota, credits,
stale/expired observations, policy scope and configured single-account semantics
MUST retain their established meanings. Derived pressure MUST NOT be persisted as
a fabricated upstream rejection. Concurrent admission MUST retain existing lease
atomicity and cleanup, including replica-partitioned capacity.

#### Scenario: Expired fallback cooldown is not quota recovery
- **GIVEN** a local admission hold expired but applicable fresh quota is exhausted
- **WHEN** a new turn is selected
- **THEN** the expired hold alone does not cause submission to that account

#### Scenario: Existing in-flight work consumes headroom
- **GIVEN** an account is near the configured budget threshold with active leases
- **WHEN** a new turn needs an account and an eligible safer account exists
- **THEN** selection includes in-flight pressure and preserves the existing
  reservation/commit-lock checks before choosing the safer account

#### Scenario: Unreliable or unrelated usage does not fabricate a hard block
- **GIVEN** a usage sample is stale, expired or not applicable to the model/credit policy
- **WHEN** new-work admission is evaluated
- **THEN** that sample alone cannot fabricate quota exhaustion for the request
