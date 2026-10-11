## Why

On 2026-10-11, PC2's Codex-LB Beta GPT-6.1 Sol/High workload encountered 24 HTTP-bridge upstream reader failures; most followed hundreds or thousands of upstream frames and lacked a WebSocket close code. The bridge reported only `stream_incomplete`, `websocket_transport_error`, and `Upstream websocket receive failed`. The native egress helper, however, sends an explicit sanitized failure phase (transport, protocol, helper exit/read/write, consumer backpressure, liveness timeout, etc.) which is currently discarded when the upstream adapter wraps the exception. Operators therefore cannot distinguish an upstream socket/network failure from the proxy's own queue saturation or helper failure. PC2's per-key `always_http` mitigation succeeded and must remain unchanged.

## What Changes

- Carry a closed-set, credential-safe native receive failure phase through `UpstreamWebSocketMessage`, without changing the normalized error code, client-visible error message, retry, accounting, health penalty, or account ownership.
- Append an optional `native_failure_phase` field to existing HTTP-bridge `reader_failure` logs; only allowlisted phase names are emitted. Never log helper raw exception text, upstream URL, credentials, or payload.
- Add adapter-level and real bridge-reader-path regression tests, including unknown/untrusted phase values, success and clean-close controls.
- No operator setting, schema migration, account switch, replay policy, or runtime image change in this packet.

## Impact and Boundaries

- Capability: `proxy-runtime-observability`.
- Files: `app/core/clients/proxy_websocket.py`, `app/modules/proxy/_service/http_bridge/upstream_events.py`, `app/modules/proxy/_service/http_bridge/helpers.py`; related unit tests.
- The packet is diagnostic and does NOT claim to repair the underlying upstream TCP/WS failure. A future occurrence should identify its class before a transport retry or helper queue change is considered.
- Candidate is based on the exact deployed Beta source commit `b948ea14d` and remains isolated until review and qualification.
