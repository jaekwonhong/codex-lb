## Why

A Codex Desktop thread can switch from an OpenAI-compatible model source such as Qwen to a subscription model such as Astra while preserving the same local history. OpenAI-compatible sources may emit plain Responses reasoning items with non-empty `reasoning_text` content or non-OpenAI reasoning IDs; forwarding those items unchanged to the subscription upstream produces deterministic invalid-request failures such as `array_above_max_length` or invalid reasoning-item IDs.

## What Changes

- Sanitize final subscription Responses payloads before egress by removing reasoning input items that cannot be replayed to the subscription upstream.
- Treat a reasoning item as non-portable when it carries non-empty `content`, or when it carries a non-empty ID that is not an OpenAI reasoning ID beginning with `rs_`.
- Preserve portable subscription reasoning items, including empty-content `rs_` items and encrypted reasoning state.
- Preserve all user, developer, assistant, tool-call, tool-output, and other input items in their original order.
- Apply the same normalization to subscription HTTP, subscription websocket, direct websocket `response.create`, retry/fresh-resend serialization, and HTTP bridge serialization.
- Leave OpenAI-compatible model-source forwarding unchanged.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `responses-api-compat`: Define subscription egress normalization for non-portable reasoning history during cross-provider thread continuation.

## Impact

- Affected code: shared Responses request utilities plus subscription transport serialization in `app/core/clients/proxy.py` and `app/modules/proxy/_service/`.
- Affected tests: focused request-normalization tests and subscription HTTP/websocket/bridge serialization regressions.
- No public endpoint, database schema, configuration, dependency, model-source, or provider-selection change.
