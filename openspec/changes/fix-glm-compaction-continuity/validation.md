# Validation

## Candidate

- Runtime source: `e9cca2448ea1efaac5573071dbbd40c0bc3bef2a`
- GLM compaction bounds change: `0f9f9fdba`
- Beta image: `codex-lb-beta:astra-glm-final-e9cca2448-20261007-r2`
- Image ID: `sha256:6c3b9f10670ca2ab15f141c89d00fed7596fe2bae44aa4c4e232f3e2c21238f9`
- Beta endpoint: localhost port 2456
- Rollback container retained from the pre-candidate Beta runtime.

The image is an overlay on the previously qualified Beta image. The runtime
diff from `d7be9d0c1` contains only the nine Python files required by the
final Astra continuity and GLM compaction changes; no runtime file is deleted.

## Static and regression validation

- GLM compaction/model-source targeted suite: 42 passed.
- Qualified GLM Compact defaults to `max_output_tokens=32768` and
  `reasoning.effort=low`.
- A lower model-source `max_output_tokens` remains authoritative.
- A lower positive `source_request_overrides.max_output_tokens` remains
  authoritative.
- API-key enforced reasoning and allowed-reasoning policy remain authoritative.
- Normal GLM requests and non-GLM compaction requests are unchanged.
- A genuine upstream `response.incomplete(max_output_tokens)` remains an
  observable incomplete terminal rather than being rewritten as success.
- Ruff check and format checks passed for the changed GLM files.
- Changed-file `ty check` passed.
- `openspec validate fix-glm-compaction-continuity --strict` passed.

## Live Beta source configuration

The enabled source `dgx-msi-glm5.3-flash` reported:

- model: `glm5.3-flash`
- Responses support: enabled
- streaming: enabled
- context window: 262,144
- max output tokens: 32,768
- reasoning support: enabled
- reasoning levels: low, medium, high
- operator source request override: none

The alternate `opencodex-dgx-msi-glm5.3-flash-beta` source was disabled
during qualification, so the live requests were served by the production
DGX Spark + MSI edgeXpert source.

## Live Compact validation

### Route-contract smoke

A Codex Desktop-compatible Responses request was sent through Beta with
`x-codex-turn-metadata.request_kind=compaction`, while the client requested
high reasoning.

Result:

- HTTP 200
- terminal: `response.completed`
- input tokens: 140
- output tokens: 119
- reasoning tokens: 7
- request log reasoning effort: `low`
- upstream status: 200
- routed model source: enabled GLM5.3 source

This proves that the compaction-only low-reasoning profile is active in the
deployed Beta runtime and that the completed terminal reaches the client.

### Long-context stress

A synthetic Codex continuity history was sent through the same compaction
contract to exercise the failure mode that previously ended with
`response.incomplete(max_output_tokens)`.

Result:

- request body size: 139,493 bytes
- elapsed time: 55 seconds
- HTTP 200
- terminal: `response.completed`
- input tokens: 44,718
- output tokens: 494
- reasoning tokens: 17
- request log reasoning effort: `low`
- upstream status: 200

No `response.incomplete`, `max_output_tokens` terminal, or stream
disconnect occurred.

### Final image smoke

After correcting the image provenance label to the exact runtime source SHA,
the `r2` image was restarted on Beta and passed:

- `/health`
- `/health/ready` including database readiness and bridge-ring membership
- a second authenticated GLM compaction request with HTTP 200 and
  `response.completed`

The final smoke used 40 input tokens, 228 output tokens, and 9 reasoning
tokens.

## Normal-turn regression observation

During qualification, Codex Desktop for Windows continued serving ordinary
GLM5.3 turns on the same source with high reasoning, including requests above
100k input tokens. This provides live confirmation that the low-reasoning
override remains scoped to compaction rather than ordinary GLM turns.

## Result

The Beta candidate satisfies the GLM compaction continuity change and is
ready to be treated as a stable candidate. Stable promotion remains a
separate deployment action.
