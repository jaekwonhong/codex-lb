# model-source-routing Delta

## ADDED Requirements

### Requirement: Source-scoped Responses fallback uses positive assigned-source ownership

A source-scoped API key MAY use ordinary subscription-backed Responses models in addition to its explicitly assigned model sources. After normal and disabled model-source lookup both miss, the proxy MUST NOT treat absence from the process model registry by itself as proof that the requested model belongs to an assigned source. For a non-empty source assignment set, the final source-only fail-closed decision MUST require that at least one source explicitly assigned to the presented API key declares the exact request model candidate that is eligible under the key's model allowlist. Source/model enablement and Responses capability MUST NOT erase that ownership evidence at this final boundary, because those routing conditions were already evaluated by the normal and disabled lookups.

When a source-scoped key has no remaining assigned source rows, an otherwise registry-unknown model MUST continue to fail closed rather than broadening provider access from an ambiguous dangling scope. A model that is present in the subscription registry MUST retain subscription precedence under the existing source-selection rules.

A structural Responses source-route exclusion MUST remain authoritative: file-pinned requests and Codex terminal-compaction requests MUST use their subscription path rather than being rejected by the final source-only guard. Likewise, when ordinary enabled-source selection finds a candidate but the existing `previous_response_id` continuity resolver suppresses that candidate in favor of a recorded subscription account owner, the final source-only guard MUST NOT override that continuity decision.

#### Scenario: Unowned registry-missing subscription model falls through

- **GIVEN** an API key scoped to source A
- **AND** source A declares only model `source-a-model`
- **AND** the process subscription registry does not contain `gpt-6-astra`
- **WHEN** the key requests `gpt-6-astra` through `/backend-api/codex/responses` or `/v1/responses`
- **THEN** model-source lookup does not select source A
- **AND** the proxy continues to subscription routing rather than returning `model_source_unavailable`

#### Scenario: Positively owned unroutable source model fails closed

- **GIVEN** an API key scoped to source A
- **AND** source A declares `source-only-model`
- **AND** no enabled Responses-capable route can serve `source-only-model`
- **AND** the subscription registry does not contain `source-only-model`
- **WHEN** the key requests that model through a Responses HTTP surface
- **THEN** the proxy returns `model_source_unavailable`
- **AND** it does not dispatch the model to a subscription account

#### Scenario: Runtime-enabled edge model remains source routed

- **GIVEN** a source-scoped API key assigned to a DB-disabled source whose id is process-locally runtime enabled
- **AND** that source declares the requested Responses model
- **WHEN** the key requests that model
- **THEN** the runtime-enabled assigned source is selected
- **AND** an unrelated subscription model is not routed to that source merely because the subscription registry omits it

#### Scenario: File pin keeps structural subscription routing

- **GIVEN** a source-scoped key whose assigned source declares the requested model
- **AND** the Responses payload contains a file pin that excludes model-source routing
- **WHEN** the request is handled
- **THEN** the source-only guard does not reject the request
- **AND** the existing subscription file-pin path remains authoritative

#### Scenario: Continuity-suppressed source candidate keeps subscription routing

- **GIVEN** a source-scoped key whose assigned source is enabled and routable for the requested model
- **AND** ordinary source selection finds that source
- **AND** the existing continuity resolver finds a recorded subscription account owner for `previous_response_id` on the same API key and suppresses the source candidate
- **WHEN** the next Responses request is handled
- **THEN** the final source-only guard does not override that continuity-suppressed decision
- **AND** the request follows the existing subscription continuity path

#### Scenario: Dangling source scope remains fail closed

- **GIVEN** an API key still marked source scoped but with no remaining assigned source rows
- **AND** the requested model is absent from the subscription registry
- **WHEN** the key requests that model through a Responses HTTP surface
- **THEN** the proxy fails closed rather than broadening the request to a subscription account


### Requirement: Integrated Beta patch packets qualify the source-scope provider boundary semantically

A Beta candidate that carries the local edge/source-scoping patch packet MUST be
qualified after Responses integration with a semantic contract that is
independent of historical commit IDs. Qualification MUST reject a candidate if
source-only classification uses subscription-registry absence without positive
model ownership by an explicitly assigned source, if the classifier cannot
perform the ownership lookup asynchronously, if a Responses HTTP caller does
not await that classifier, or if the final guard can override a structural
source-route exclusion or an already continuity-suppressed subscription owner.
The qualification MUST also preserve the dangling empty-assignment fail-closed
boundary. The `glm5.3-flash` encrypted-reasoning replay adaptation MUST be
qualified by model capability rather than a deployment-specific model-source
row id so recreating or moving the single DGX Spark + MSI edgeXpert cluster source does not
silently disable the adaptation.

#### Scenario: Historical registry-only integration is rejected

- **GIVEN** a candidate whose source-scoped classifier treats registry absence as source ownership
- **AND** its Responses HTTP handlers use that classifier as the final provider-boundary guard
- **WHEN** Beta patch-packet qualification runs
- **THEN** qualification fails before deployment

#### Scenario: Ownership-aware integrated packet qualifies

- **GIVEN** source-only classification positively checks model declaration inside the presented key's assigned sources
- **AND** dangling scope remains fail closed
- **AND** both Responses HTTP guards await the classifier while preserving source-route exclusions and continuity suppression
- **WHEN** Beta patch-packet qualification runs
- **THEN** the source-scope semantic contract passes regardless of the candidate's rebased commit IDs

#### Scenario: Recreated edge source keeps Responses replay adaptation

- **GIVEN** `glm5.3-flash` is served by one model-source endpoint backed by DGX Spark rank 0 and MSI edgeXpert rank 1
- **AND** that model-source row is recreated with a different source id
- **AND** the Responses history contains provider-encrypted reasoning content
- **WHEN** the request is forwarded to the edge-served model
- **THEN** the unsupported encrypted reasoning field is removed before forwarding
- **AND** qualification does not require any historical source id
