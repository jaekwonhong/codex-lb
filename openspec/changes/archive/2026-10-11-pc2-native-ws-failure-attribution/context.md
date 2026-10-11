# Diagnostic scope and operational interpretation

The 2026-10-11 PC2 incident used Codex-LB Beta 2456 with model gpt-6.1-sol / reasoning high. At least 24 HTTP-bridge `reader_failure` events were recorded between 14:02 and 15:18 KST, most after receiving output and without an upstream close code. Upstream error messages were flattened into `Upstream websocket receive failed`. The same session family subsequently experienced `previous_response_not_found`, `previous_response_owner_unavailable`, and `usage_limit_reached` errors.

The approved user-scoped mitigation is `always_http` for the PC2 Beta API key. A real GPT-6.1 Sol / High request then succeeded over HTTP at 16:01:20 KST. The mitigation must not be rolled back merely to elicit a failure.

Native egress already carries `failure_phase`. This patch retains a fixed diagnostic subset of that attribute through the Python WebSocket wrapper into the existing bridge reader-failure event. The field can distinguish upstream socket I/O (`transport`), native wire protocol (`protocol`), helper lifecycle (`helper_exit`, `helper_read`, `helper_write`), and local consumer backpressure (`consumer_backpressure`). None of these is a final attribution of network equipment, remote API service, or process owner.

## Operational usage

After a separately qualified Beta deployment of this diagnostic patch, future `http_bridge_event event=reader_failure` lines can be grouped by `native_failure_phase` and correlated with `response_events_seen`, transport classification, and their corresponding request-log failures. Diagnostic phase `None` means no approved native phase was available; it must not be called a normal close or proof of a specific cause.

No request is retried solely because of this diagnostic. A mid-output failure may be ambiguous upstream and must retain existing fail-closed semantics; only the existing bounded, formally proven replay rules may resume. No account switch or client-history recreation is authorized by this patch.

This patch does not require a runtime container change to be safely implemented and tested. Deployment requires the usual signed/single-writer runtime promotion and rollback checks and should not interrupt the currently healthy PC2 session.
