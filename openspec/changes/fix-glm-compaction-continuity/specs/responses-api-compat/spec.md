## ADDED Requirements

### Requirement: Qualified GLM compaction uses a bounded output budget

Source-routed `glm5.3-flash` Responses requests tagged
`request_kind = "compaction"` MUST use a default
`max_output_tokens = 32768`. A lower positive enabled model-source
`max_output_tokens` or operator
`source_request_overrides.max_output_tokens` MUST win. This budget policy
MUST NOT change non-compaction GLM requests or requests for other models.

#### Scenario: GLM compaction receives the qualified output budget

- **GIVEN** `glm5.3-flash` is configured with `max_output_tokens = 32768`
- **WHEN** Codex sends a source-routed Responses turn tagged `request_kind = "compaction"`
- **THEN** the source payload MUST contain `max_output_tokens = 32768`

#### Scenario: Lower source output ceiling wins

- **GIVEN** the enabled source model has `max_output_tokens = 16384`
- **WHEN** a GLM compaction request is forwarded
- **THEN** the source payload MUST contain `max_output_tokens = 16384`

#### Scenario: Operator output cap wins over the compaction default

- **GIVEN** `glm5.3-flash` has `source_request_overrides.max_output_tokens = 8192`
- **WHEN** a GLM compaction request is forwarded
- **THEN** the source payload MUST contain `max_output_tokens = 8192`
- **AND** the 32,768-token compaction default MUST NOT raise the operator cap

#### Scenario: Normal GLM request keeps its output budget

- **WHEN** a `glm5.3-flash` Responses request is not tagged as compaction
- **THEN** this compaction policy MUST NOT alter its output-token budget

### Requirement: Qualified GLM compaction uses low reasoning when policy permits

Source-routed `glm5.3-flash` compaction requests MUST use
`reasoning.effort = "low"` when no API-key reasoning policy is active.
`enforcedReasoningEffort` MUST win. An active `allowedReasoningEfforts`
policy MUST preserve existing client authorization and omitted-effort behavior.

#### Scenario: GLM compaction receives low reasoning by default

- **GIVEN** no API-key reasoning policy is active
- **WHEN** a GLM compaction request is forwarded
- **THEN** the source payload MUST contain `reasoning.effort = "low"`

#### Scenario: API-key reasoning enforcement wins over the compaction default

- **GIVEN** an API key whose `enforcedReasoningEffort` is `high`
- **WHEN** the same GLM compaction request is forwarded
- **THEN** the source payload MUST preserve `reasoning.effort = "high"`

#### Scenario: API-key allowlist preserves omitted-effort behavior

- **GIVEN** an API key with `allowedReasoningEfforts: ["low"]`
- **AND** the client omits `reasoning.effort`
- **WHEN** the GLM compaction request is forwarded
- **THEN** the proxy MUST NOT inject a reasoning effort

#### Scenario: Normal GLM request keeps its reasoning effort

- **WHEN** a `glm5.3-flash` Responses request is not tagged as compaction
- **THEN** this compaction policy MUST NOT alter its reasoning effort

### Requirement: Model-source incomplete terminals are preserved

A model-source `response.incomplete` event MUST remain an upstream terminal
event through source stream classification and public Responses streaming. The
proxy MUST NOT convert a genuine incomplete terminal into
`response.completed`, and MUST NOT report a transport disconnect solely
because the terminal kind is incomplete.

#### Scenario: Upstream max-output incomplete remains observable

- **GIVEN** a source emits `response.incomplete` with
  `incomplete_details.reason = "max_output_tokens"`
- **WHEN** the source-routed Responses stream is relayed
- **THEN** the client receives the incomplete terminal
- **AND** source settlement records terminal kind `incomplete`
