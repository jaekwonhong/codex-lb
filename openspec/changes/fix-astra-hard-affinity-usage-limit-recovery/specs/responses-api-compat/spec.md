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

### Requirement: Definitive owner-quota relocation has one transport-independent policy boundary

Any direct HTTP stream or HTTP-bridge path that would move a continuity-owned request to another account after definitive owner quota exhaustion MUST obtain a movable verdict from the shared relocation policy before clearing the owner requirement, excluding the owner, or dispatching on a replacement account. A locally verified fresh body alone MUST NOT authorize cross-account movement. Generic configured required-account routing that is not an ownership or continuity constraint MUST retain its existing non-continuity selection and degraded-mode semantics.

#### Scenario: Selection-time owner quota uses the shared verdict

- **GIVEN** a direct HTTP continuation has locally verified account-neutral full-resend material
- **AND** required-owner admission proves the continuity owner is definitively quota-exhausted before any upstream dispatch
- **WHEN** another account is eligible
- **THEN** the proxy MUST consult the shared relocation verdict before releasing the owner pin
- **AND** it MAY dispatch on the replacement only when that verdict is movable

#### Scenario: Generic required account is not continuity provenance

- **GIVEN** routing is configured with a required account for non-continuity reasons
- **WHEN** that account is unavailable or quota-exhausted
- **THEN** selection MUST preserve the existing generic required-account error and degraded-mode semantics
- **AND** it MUST NOT fabricate definitive continuity-owner quota provenance

### Requirement: HTTP-bridge owner-quota relocation re-fences durable continuity on the replacement

When an HTTP-bridge continuation receives a pre-visible definitive `usage_limit_reached` from its owner and the shared relocation verdict authorizes an account-neutral full resend, the retry MUST clear the exhausted request's hard anchor and owner pin, exclude the exhausted owner, and re-bind the existing durable operation dedupe identity to the replacement owner before the retry is dispatched. The reallocation authority MUST be request-local and MUST NOT weaken later ordinary reconnects. A subsequent continuation anchored to the replacement response MUST remain on that replacement account.

#### Scenario: Full resend relocates and the following turn stays on the replacement

- **GIVEN** account A owns a completed Astra turn and the client sends a verified complete full resend for the next turn
- **WHEN** account A returns pre-visible `usage_limit_reached`
- **AND** account B is eligible and the shared relocation verdict is movable
- **THEN** the proxy retries the account-neutral full resend on account B without the exhausted `previous_response_id`
- **AND** the durable operation is re-fenced on account B before dispatch
- **AND** a following request anchored to account B's response continues on account B rather than reconnecting to account A
