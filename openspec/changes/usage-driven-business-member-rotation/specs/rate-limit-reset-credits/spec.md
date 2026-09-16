## ADDED Requirements

### Requirement: Rotation resolves reset credits through the authoritative redemption path

When a Business member has confirmed fresh Weekly exhaustion, rotation SHALL resolve reset-credit availability through the existing rate-limit reset-credit authority and SHALL reuse its per-account cross-replica serialization, durable redeem-request pinning, selected-credit identity, cache invalidation, and usage-refresh behavior. A convenience/account-summary value that presents missing reset-credit data as `0` SHALL NOT by itself prove that no reset credit exists. An absent detail snapshot likewise SHALL be `unknown` unless a fresh authoritative resolution proves no redeemable credit.

One rotation evaluation SHALL issue at most one upstream reset-credit consume attempt and SHALL use one stable `redeem_request_id` for that attempt. Rotation SHALL NOT add a second redemption executor or a loop that consumes additional credits to resolve ambiguity.

#### Scenario: Summary zero is not authoritative absence
- **GIVEN** the account summary exposes `available_reset_credits: 0`
- **AND** the detailed reset-credit authority has no fresh snapshot proving zero redeemable credits
- **WHEN** an exhausted member is evaluated for rotation
- **THEN** reset-credit state is unresolved rather than confirmed absent
- **AND** member replacement is not authorized from the summary value alone

#### Scenario: Concurrent reset use shares the existing serializer
- **GIVEN** a manual/reset scheduler path and rotation both try to redeem for the same account
- **WHEN** rotation reaches reset-credit resolution
- **THEN** it uses the same shared-database serialization and durable request pinning as the existing redemption path
- **AND** it does not consume a second credit merely because another path is in progress

### Requirement: Reset response and usage recovery are separate evidence

Rotation SHALL evaluate the reset-credit response code and `windows_reset` separately from subsequent usage recovery. A convenience top-level status SHALL NOT by itself prove Weekly recovery. After a reset or idempotently successful redemption, rotation SHALL perform a bounded series of fresh usage observations to determine whether the actual Weekly window recovered. An immediately unchanged/exhausted Weekly value SHALL NOT authorize replacement because propagation may be delayed. If bounded reconciliation cannot prove recovery or a safe no-reset outcome, rotation SHALL stop in an attention/pending state and SHALL NOT consume another credit or proceed to member removal.

#### Scenario: Reset reply arrives before Weekly propagation
- **GIVEN** a reset-credit consume returns a reset-success code with at least one applicable window reset
- **AND** the first fresh usage read still reports the prior exhausted Weekly value
- **WHEN** rotation reconciles the result
- **THEN** it performs only the bounded follow-up reads defined by the implementation contract
- **AND** it does not start member replacement from that first unchanged value

#### Scenario: Reset outcome remains unresolved
- **GIVEN** one reset-credit attempt was admitted
- **WHEN** its response or subsequent Weekly observations cannot establish a safe terminal result within the bounded reconciliation
- **THEN** the rotation evaluation stops as attention/pending
- **AND** no second reset-credit consume, member removal, or invitation is issued automatically
