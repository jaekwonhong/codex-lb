## ADDED Requirements

### Requirement: Fresh WebSocket reattachment uses proven complete context when possible

When a hard-continuity HTTP bridge opens a **new** upstream WebSocket, it MAY replace a server-injected completed response anchor with a verified full-context request. It MUST require completed, bounded, same-session and same-owner durable evidence. It MUST keep owner admission and all operation fences unchanged. Unproven context MUST NOT be dropped.

#### Scenario: Complete recorded conversation after an upstream socket disconnect
- **GIVEN** a completed durable parent-response chain whose final turn matches the exact response id, durable session and original owner
- **AND** an account-neutral, complete reconstruction of a delta-only client request with no external or unmatched tool references
- **AND** the last completed response is still the most recent persisted operation on that session (no later partial or ambiguous turn)
- **WHEN** a new upstream WebSocket must be opened
- **THEN** the bridge can reconstruct and dispatch the complete context without previous_response_id
- **AND** no later session-level, durable, or owner-forward reattach path may re-inject the retired response id
- **AND** the bridge continues to require its original account and operation identity protections

#### Scenario: Interrupted prior response or absent transcript
- **GIVEN** the parent chain has incomplete output, missing or mixed-owner last turn, truncated spool, absent anchor, oversized transcript, account-scoped state, a newer uncertain operation, or an unverifiable reconstruction
- **WHEN** the client sends a delta
- **THEN** the bridge MUST NOT dispatch a context-stripped fresh request or present a reconstructed history as proven
- **AND** the existing continuity error/owner-bound behavior is preserved

#### Scenario: Error after a current response began
- **GIVEN** response.created or output was already observed for the current turn
- **WHEN** WebSocket receive fails
- **THEN** the new reconstruction feature MUST NOT replay that turn, swap accounts, or double-execute tools
