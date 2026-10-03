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

### Replacement candidate after the pre-promotion corrections

The reviewed corrections were committed as
`aa059dea8bc1c27f70f42b1a4fb9a11a9f2a74dc` and fast-forwarded locally into
`codex/main-d1fd-patch-packet-20260917`. No remote push was performed.

A new minimal derivative was built from the unchanged production Beta base
`sha256:8d606b5add93fd526a3e7a2af4c56ac2dd7c176f74a1e67c316e9069ce2c8c48`:

- image: `sha256:c3fdb1b9f9935574476e66d47a401a12f06bdeac836d3cd82fd4f51b3917a34d`
- revision label: `aa059dea8bc1c27f70f42b1a4fb9a11a9f2a74dc`
- scope label: `pc2-owner-recovery-stage1-reviewed`
- four-file bundle SHA-256:
  `a721aecf98d41134d9cdc2a8328f830353c6afa5ac1ebc03d51c1b83255a87ff`
- `api.py`: `3f984c233bb96289bf4651e883363db71b83a478c4ed932ee00ff8f4523d3913`
- HTTP-bridge `helpers.py`:
  `476ec7a7d901171e1938b2a079a8af527099647b91cb52990227c1460553866e`
- HTTP-bridge `streaming.py`:
  `d9032774553e3be16a87e74dc2b21a60e81d7fa45301cf1765eb5a4e21e68642`
- `_service/request_log.py`:
  `eda40b753f62f416a98b35198234f11390eb39053f3fcce67aae735b92b8e483`

All four hashes match byte-for-byte between the committed worktree and the
image. In-image smoke reconfirmed HTTP 400 + `continuity_recovery_required` +
`x-should-retry:false`, the committed-SSE `invalid_prompt` surrogate with
`availability_reason=continuity_recovery_required`, no retry directive, and the
one-second bounded preflight-log acknowledgement constant.

### Production Beta promotion

After explicit user authorization, the reviewed candidate was promoted to Beta
through a one-shot transaction that cloned the running Beta's actual
Config/HostConfig/mount contract and changed only the image. The repository's
older `scripts/recreate_beta.sh` was not used because its image/socket/release
pins no longer describe the current Beta9 production topology.

- promoted Beta container:
  `2519dacb15ef0ccec8f22c522db81528b633372784e97bde3cfbe31971ef77f4`
- promoted image:
  `sha256:c3fdb1b9f9935574476e66d47a401a12f06bdeac836d3cd82fd4f51b3917a34d`
- retained rollback predecessor:
  `0d90b2bbc7ec6a521a72baee3793d90dc62857433aef5456d29910f8a6f14eb9`
  as `codex-lb-beta-pre-continuity-20261003T093239Z-46333`, stopped with
  `restart=no`
- Stable remained container `0c717ce1...` on image `sha256:11eb4370...`
- PostgreSQL remained container `1e42fec6...`, system identifier
  `7684501606386458669`, Alembic head
  `20260913_000000_add_oidc_provider_flow`

Post-promotion qualification returned `PASS_PROMOTED_BETA_QUALIFICATION` both
immediately after cutover and after a Beta-only restart used to clear synthetic
canary state. Local and tailnet Beta/Stable readiness were all HTTP 200, the four
runtime application hashes matched the reviewed image, startup/runtime error
markers were zero, nonterminal durable operations were zero, and unexpired
session leases were zero. The recreation lock was released normally.

Two server-generated live canaries were attempted while investigating whether the
Stage-1 branch could be exercised without direct PC2 control. Neither is product
qualification: the first supplied only an existing turn-state and the second used
the raw thread id with a synthetic process-session value. Both therefore resolved
to fresh synthetic continuity identities and completed normally on an active
account rather than entering the intended fresh-reattach owner-unavailable branch.
No retained HTTP-bridge operation was created. The two synthetic durable sessions
and their four aliases were then removed after proving they owned no operation or
recovery-attempt rows; the original rate-limited target session and its turn-state
alias remained intact. Beta was restarted on the same promoted container/image to
clear the in-process registry, and the full post-promotion qualifier passed again.

The actual PC2 Desktop product-path gate therefore remains outstanding. It requires
the real Desktop process-session identity; synthetic server calls MUST NOT be used
as a substitute for that evidence.

### Actual PC2 Desktop 0.160 result and residual defect

The product-path gate was subsequently exercised from the real PC2 Codex Desktop
on conversation `01a10030-...`. At 2026-10-03 10:25:09 UTC the promoted Beta
returned `502 previous_response_owner_unavailable` before upstream dispatch
(`http_bridge_routing stage=admission reason=smart_session`). This is a genuine
Stage-1 qualification failure for image `sha256:c3fdb1b9...`, not a synthetic
canary result.

The prior successful response was attributable under proxy API-key id
`1c6c7caa-...`; the failing Desktop 0.160 request arrived under API-key id
`ee0a3000-...`. Previous-response owner lookup is intentionally API-key scoped, so
the proxy correctly did not reuse owner proof across those scopes. The defect was
the public contract after that safe lookup miss: an unchanged retry cannot restore
the missing owner proof, yet the native client received a transient-looking 502.

The follow-up source correction keeps API-key isolation intact and changes only
the native backend pre-dispatch outcome. An explicit previous-response owner-proof
miss now raises the same typed local recovery refusal from both HTTP-bridge
admission and the raw-HTTP fallback. The raw path writes the same bounded,
NULL-account preflight log; SDK/non-native behavior remains unchanged.

Follow-up validation after this correction:

- actual-shape owner-interruption suite: 31 PASS
- core native/SDK/bridge/ownership/source matrix: 1,274 PASS
- extended HTTP/native-egress/model-source routes: 355 PASS, 319 SKIP for the
  still-unconfigured external native-egress binary, 0 FAIL
- Ruff, format, targeted typing, proxy architecture, cancellation-safety and
  `git diff --check`: PASS
- strict changed-spec validation: PASS; complete OpenSpec validation: 156 PASS,
  0 FAIL

The running production Beta remains the earlier `c3fdb1b9...` image until a new
follow-up candidate is committed, built, reviewed and separately authorized for
promotion. Stage 2 remains blocked on the corrected candidate passing the actual
PC2 Desktop path.
