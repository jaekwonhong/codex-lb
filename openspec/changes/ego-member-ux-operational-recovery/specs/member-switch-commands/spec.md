## ADDED Requirements

### Requirement: Catalog failures are recoverable without authorizing stale actions
The UI SHALL show workspace-specific recovery guidance and raw diagnostic code when owner membership observation fails. Preview and OAuth enrollment SHALL remain disabled for that workspace until a trusted observation is available. A failure in one workspace SHALL NOT disable a separately confirmed workspace.

#### Scenario: Owner login needs assistance
- **WHEN** catalog refresh returns an owner login-required code for one workspace
- **THEN** that workspace identifies the owner login recovery path and disables candidate selection
- **AND** a successfully observed workspace remains usable

### Requirement: Live catalog access requires confirmed stored state
The hook and UI SHALL refuse live catalog refresh after a failed stored-state restoration or unresolved creation response until a stored-state refresh succeeds. Automatic post-finish catalog refresh SHALL require an accepted completed result.

#### Scenario: Creation reply is lost
- **WHEN** creation may have been accepted but its response is lost
- **THEN** no fresh catalog or second create command is sent before stored-state reconciliation

### Requirement: Runtime certainty is explicit
Ego result parsers SHALL require correctly typed success, code, profile and outcomeUnknown fields. Missing, malformed or contradictory certainty fields SHALL yield a sanitized unknown result rather than a known success or failure, and SHALL NOT discard pending intent or authorize a retry.

#### Scenario: Runtime omits uncertainty
- **WHEN** a runtime reply lacks outcomeUnknown
- **THEN** the exact participant command remains pending across restart with no second browser execution

### Requirement: The runtime deadline covers script delivery
The configured Ego operation timeout SHALL cover stdin delivery, concurrent stdout/stderr consumption, and process completion. A helper that stops reading stdin SHALL not block beyond the operation deadline merely because the caller has no cancellation token. Cancellation SHALL terminate the owned process and observe its stream tasks.

#### Scenario: Helper never reads the script
- **WHEN** script delivery blocks because the helper does not consume input
- **THEN** the operation returns a sanitized timeout with unknown outcome and does not replay the command
