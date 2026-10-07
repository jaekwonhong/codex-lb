# Change: Preserve GLM compaction continuity

## Why

Codex Desktop compaction against the private `glm5.3-flash` source can end as
`response.incomplete` with `reason=max_output_tokens`. Codex then surfaces
that terminal as a disconnected/incomplete Compact and the active conversation
cannot complete its optimization step.

The Beta workaround already gives qualified GLM compaction turns a 32,768-token
generation budget and lowers reasoning effort so the summary has more room.
That profile must also preserve lower source/operator output ceilings and
API-key reasoning policy instead of overwriting them after normal source
request shaping.

## What changes

- Keep the GLM compaction default at `max_output_tokens=32768` and
  `reasoning.effort=low`.
- Bound that output budget by any lower enabled model-source
  `max_output_tokens` or operator
  `source_request_overrides.max_output_tokens`.
- Preserve active API-key `enforcedReasoningEffort` and
  `allowedReasoningEfforts` policy instead of injecting the compaction
  default over it.
- Keep the existing TensorFold compatibility scrub for
  `reasoning.encrypted_content`.
- Keep normal GLM turns and all non-GLM source requests unchanged.

## Impact

- The source request stays within the real DGX+edgeXpert serving ceiling while
  maximizing room for Compact output.
- Operator and API-key policy continue to have higher precedence than the
  GLM-specific default.
- No context-window, persistence, schema, or ProviderSwitcher-client behavior
  changes.
