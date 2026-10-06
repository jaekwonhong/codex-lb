## ADDED Requirements

### Requirement: Direct turn-state quota recovery requires verified full resend

A direct streaming Responses request MAY move off a registered turn-state owner after pre-visible `usage_limit_reached` only when the exact API-key-scoped local bridge proves the incoming body is a complete account-neutral resend. Missing proof or any hard account-scoped dependency MUST remain fail-closed.

#### Scenario: Registered turn state qualifies with complete retained context

- **GIVEN** a registered `http_turn_*` alias belongs to account A
- **AND** the local bridge proves the request contains its completed input prefix, retained prior output, and fresh account-neutral input
- **WHEN** account A returns pre-visible `usage_limit_reached`
- **THEN** the request is eligible for guarded cross-account recovery

#### Scenario: Incomplete or account-scoped history stays pinned

- **GIVEN** a registered turn-state belongs to account A
- **WHEN** the request omits required prior output or references account-scoped files, images, conversation state, or unresolved tool state
- **THEN** the request MUST NOT replay on another account under this recovery contract

### Requirement: Verified turn-state recovery revalidates and removes the exhausted token

Before moving a qualified turn, the proxy MUST revalidate the same local session, owner, alias generation, stored input anchor, and pending-tool manifest. It MUST exclude the exhausted owner, remove `x-codex-turn-state`, and resume through ordinary thread/session affinity. A changed proof or single-account routing MUST remain fail-closed.

#### Scenario: Unchanged proof retries without the exhausted turn state

- **GIVEN** a qualified registered turn-state full resend on account A
- **AND** account B is eligible
- **WHEN** the alias/session/input proof is unchanged at the quota failure
- **THEN** the proxy excludes account A and retries on account B
- **AND** replacement dispatch does not forward the exhausted `x-codex-turn-state`

#### Scenario: Concurrent anchor advance cancels recovery

- **GIVEN** a registered turn-state request was initially verified for recovery
- **WHEN** its alias, owner, stored input anchor, or pending-tool manifest changes before the quota failure is handled
- **THEN** the proxy MUST NOT cross accounts under the stale proof
- **AND** hard turn-state continuity remains authoritative
