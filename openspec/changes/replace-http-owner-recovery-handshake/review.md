# Review of ab78561f1

Scope: review and correct the stage-1 error contract. No checkpoint capture,
automatic transcript reconstruction, production deployment, or account mutation
is authorized by this review implementation.

## Confirmed findings

1. HTTP 409 is described as non-retryable, but standard OpenAI SDK retry policies
   include 409. Replace it with a distinct 400 invalid-request refusal and a
   narrowly generated no-retry response header. Do not reuse
   `previous_response_not_found`.
2. The new branch lacks a native-client/backend-contract gate and can therefore
   change SDK or `/v1` behavior. Require the existing native identity and SSE
   contract signals at the new branch only.
3. Adding the new code to the code-only preflight log set can classify a
   same-named upstream failure as an unsubmitted NULL-account request. Require
   local pre-dispatch provenance for this code; keep existing codes unchanged.
4. The message says only local recovery can help, although the original owner's
   recovery may restore the existing thread. Describe both paths and do not
   require users to delete the original thread or strip its anchor.
5. A local refusal that arrives after HTTP headers are committed cannot safely
   retain the custom `continuity_recovery_required` code in `response.failed`:
   native Codex classifies unknown failed-event codes as retryable. Use
   `invalid_prompt` only as the committed-stream transport surrogate, preserve
   the actionable recovery message, and retain
   `availability_reason=continuity_recovery_required` for raw-event attribution.
   The normal pre-commit JSON path remains the custom HTTP 400 contract.

## Verification boundary

The previous `a0a5b676...` image belongs to ab78561f1 and MUST NOT be promoted.
The corrected source has now passed focused unit/integration, SDK retry,
full-resend, model-source, Ruff/format, targeted typing, architecture,
cancellation-safety and strict OpenSpec validation. Native PC2 Desktop behavior
is still not proved by a test User-Agent or by the Python SDK and remains a
post-deploy product-path gate.

## Corrections applied in the isolated working tree

- `helpers.py`: actionable recovery message and a typed local-provenance predicate.
- `streaming.py`: native identity/contract gating, 400 refusal, provenance-qualified
  preflight accounting. No owner reassignment or dispatch rule is loosened.
- `api.py`: local-only no-retry header and suppression of contradictory retry
  hints on JSON and already-committed SSE. A committed native SSE refusal uses
  the non-retry `invalid_prompt` wire category because Codex retries unknown
  `response.failed` codes. Unmarked provider errors retain their policy.
- Existing route/unit tests updated; `test_local_history_recovery_contract.py`
  exercises the official SDK with MockTransport, local provenance, headers and
  the committed native SSE path through final stream normalization.

## Validation results and scope limits

- `test_local_history_recovery_contract.py` + API error-shaping unit tests: 40 PASS.
- Owner/replay/reattach focused HTTP bridge tests: 46 PASS.
- Owner interruption product-route integration: 15 PASS.
- Full-resend owner/replay/reattach integration subset: 25 PASS.
- Model-source WebSocket guard: 18 PASS.
- Current-tree combined regression (`local_history_recovery_contract`, API
  WebSocket auth, HTTP bridge unit coverage, owner interruption integration):
  1,121 PASS.
- Full `test_http_responses_bridge.py` together with the model-source WebSocket
  guard, proxy-architecture checker and cancellation-safety checker: PASS.
- Ruff, format, targeted `ty`, `git diff --check`, proxy architecture and
  cancellation-safety: PASS.
- Strict change validation: PASS; main OpenSpec tree: 66 PASS, 0 FAIL.
- The SDK MockTransport test sends exactly one request for the corrected 400
  refusal and demonstrates that the superseded 409 fixture retries.
- Current public Codex source confirms that HTTP 400 is terminal in the HTTP
  transport retry policy and `InvalidPrompt` has no retry delay, while an unknown
  `response.failed` code becomes retryable. That is why the committed-SSE path
  uses the narrowly scoped `invalid_prompt` wire surrogate.

The route tests exercise real API/logging layers with mocked owner/bridge
evidence. They are not a real PC2 Desktop E2E or proof of automatic account
transfer correctness. No runtime container was changed by this review pass.

A non-promotable review image was built from the exact current production Beta
image (`8d606b5a...`) by replacing only `api.py`, `helpers.py`, and `streaming.py`.
Its image id is `87b15bc9...`; all copied file hashes match the worktree and an
in-image smoke verified both the JSON and already-committed SSE contracts. The
image was built from an uncommitted tree, so it remains evidence only and is not
a release/promotion candidate even after the corrected source is committed.

Stage 2 remains unimplemented: this change does not capture a durable independent
checkpoint, protect its parent chain from retention, or reconstruct missing delta
history. It prevents a misleading client-recovery contract; it does not make all
quota-bound legacy conversations recover transparently.
