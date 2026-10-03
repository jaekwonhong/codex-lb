# Stage 1 continuity recovery reviews

Scope: review and correct the stage-1 error contract. No checkpoint capture,
automatic transcript reconstruction, production deployment, or account mutation
is authorized by this review implementation.

## Initial review of ab78561f1

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

## Pre-promotion review of 271b5354d

The preceding pass did not cover the following real failures. The candidate image
`sha256:f51b1047b8c221ad75bda586b4ea4e643080d268b3233b34c3bcf477d286838d`
MUST NOT be promoted; its source requires these additional corrections.

### Findings and corrections

1. **Unsafe late-admission retirement (high impact).** When initial owner advice
   timed out or missed new pressure, session creation could reject the owner and
   enter `retire_unavailable_continuity_owner`. That legacy branch removed the
   proxy anchor and attempted creation again with only the unproven delta. A
   public-route regression reproduced the second call using an unavailable-owner
   admission error and an affirmative retirement result. The new guard keeps
   native, client-unanchored, proxy-anchored nonportable turns pinned, including
   this late-failure path. One bounded read-only recheck can produce the explicit
   recovery refusal with positive alternate evidence. No evidence, timeout,
   failed recheck, or a different-owner result preserves the original failure;
   none permits retirement, anchor clearing or a second session-creation attempt.
   Explicit anchors, file pins, SDK contracts and proved full resends retain
   their existing paths.
2. **Originator-only attribution was missing.** Recovery admission recognized
   native `originator`, but the generic request-log helper extracted thread-id
   only for Codex-prefixed User-Agents. The local-refusal branch now uses the
   existing Codex backend identity parser for its conversation id; other log
   attribution is unchanged. The route regression also checks the ingress
   request-id, one NULL-account row and one redacted structured refusal event.
3. **The promised persistence ordering was not implemented.** Awaiting the
   preflight writer only scheduled a detached insert. The shared async-client
   fixture drained persistence after every response, hiding the wire-order race.
   New tests bypass that fixture hook. This refusal now opts into a one-second
   acknowledgement wait on the existing scheduler-owned insert, shielded against
   wait timeout/caller cancellation. The pending insert stays tracked and is not
   resubmitted. Failed or stalled logging does not replace the refusal or skip
   exactly-once reservation release. The bounded wait is deliberately limited to
   this terminal error path; ordinary success/SDK logging remains detached.

### Reproduction and scope

- Before correction, the first route expansion failed 6 of 9 cases: 2 missing
  conversation ids and 4 unsafe retirement/retry attempts.
- With the fixture response hook disabled, delayed-ack and acknowledgement-timeout
  regressions failed against the detached-only implementation.
- Corrected owner-interruption route coverage: 28 PASS, including delayed/failed/
  timed-out logging, cancellation, a real API committed-SSE boundary, and native
  identity/alternate evidence variations. The committed route preserves a single
  terminal `invalid_prompt`, the continuity marker, and one reservation release.
- Core combined regression: 1,271 PASS. Includes owner/replay/reattach, forwarding,
  native/SDK contracts, request-log virtual time, model-source WebSocket guards,
  and ProviderSwitcher service-tier headers.
- Extended routes: 355 PASS (196 HTTP bridge, 119 model-source routing,
  29 model-source dispatch, 11 native-egress tests not requiring the external
  binary). A further 319 native-egress wire probes were SKIPPED because
  `CODEX_LB_NATIVE_EGRESS_TEST_BINARY` was not configured. They are not counted as
  passes, and the Rust egress broker was not rebuilt or qualified by this review.
- Ruff, format, targeted typing for all four overlay application files, proxy
  architecture, cancellation-safety and diff checks: PASS. Strict OpenSpec change
  validation: PASS; full spec validation: 66 PASS, 0 FAIL.
- Full JUnit results and logs are retained outside Git under
  `artifacts/pc2-owner-final-review-20261003/` in the host project root.
- The newly overlaid `request_log.py` baseline was compared against the exact
  production Beta base; both SHA-256 values were
  `10483dd3d488266e743388bf16126419bffb7887df069aac9fc0621404dff681`.

The suspected owner-forward provenance loss was not changed: the actual local
recovery producer excludes `forwarded_request`, so it cannot originate at the
internal receiver under this contract. No speculative forwarding protocol was
introduced. These tests use controlled owner/upstream evidence, not the live PC2
Desktop. This review does not authorize production promotion or implement Stage 2.

### Packaging boundary after this review

The pre-promotion findings above were produced on top of reviewed source commit
`271b5354d256360e0cee359e5cab09631087f5e3`; therefore the previously built
`f51b1047...` derivative does **not** contain them and remains disqualified.

Any replacement candidate MUST be built only after these reviewed corrections are
committed and safely integrated. Its minimal overlay requires **four** application
files: `api.py`, HTTP-bridge `helpers.py` and `streaming.py`, and
`_service/request_log.py`. All four source/image hashes plus revision/base labels
MUST be reverified. Production promotion and actual PC2 Desktop qualification
remain separate gates, and the skipped Rust wire probes are not executed evidence.
