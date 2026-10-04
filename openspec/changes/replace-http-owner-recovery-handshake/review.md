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

### Follow-up candidate for the actual PC2 0.160 defect

The follow-up correction was committed as
`677128a72265766bd98f67494b7182a1a085b99f` and fast-forwarded locally into
`codex/main-d1fd-patch-packet-20260917`. No remote push was performed.

The four follow-up application files were first compared between parent source
`4dc672158...` and running production image `sha256:c3fdb1b9...`; every SHA-256
matched, so the production image is an exact packaging base for this delta.

The new unpromoted candidate is
`sha256:b57e00a806013619d0c122a20ef28116b1c81ea3e3123226af1ecd51f053ab2e`,
built from exact base `sha256:c3fdb1b9f9935574476e66d47a401a12f06bdeac836d3cd82fd4f51b3917a34d`
with revision `677128a72265766bd98f67494b7182a1a085b99f`. Its four-file bundle
SHA-256 is `fc238da018b317261d46fc30f99587aea0f0d26a4b17101d0ffa53bbb3699589`.

Source and image hashes match byte-for-byte for `continuity.py`, HTTP-bridge
`helpers.py`, HTTP-bridge `streaming.py`, and raw streaming `retry.py`. In-image
smoke reconfirmed HTTP 400 + `invalid_request_error` +
`continuity_recovery_required`, `x-should-retry:false`, and no Retry-After or
Retry-After-Ms.

### Follow-up production promotion

After explicit authorization, candidate `sha256:b57e00a8...` was promoted to
Beta using the same rollback-safe transaction pattern as the first Stage-1
deployment. The predecessor `sha256:c3fdb1b9...` was retained stopped with
`restart=no` as container `2519dacb...` under
`codex-lb-beta-pre-explicit-owner-recovery-20261003T105655Z-60236`.

The new running Beta is container `40fce5b7...` on image
`sha256:b57e00a806013619d0c122a20ef28116b1c81ea3e3123226af1ecd51f053ab2e`.
Its runtime configuration projection matches the predecessor apart from the
image/provenance/restart state, the four application hashes match the reviewed
source, local and tailnet readiness are HTTP 200, Stable is unchanged, and
PostgreSQL remains system identifier `7684501606386458669` at Alembic head
`20260913_000000_add_oidc_provider_flow`. Nonterminal operations and unexpired
leases are both zero.

Startup-log qualification found no actual `ERROR`, `FATAL`, `PANIC`,
`Traceback`, migration-failure, or schema-mismatch records. A preliminary
case-insensitive grep counted four lines only because the Uvicorn logger is named
`uvicorn.error`; those lines were ordinary INFO startup messages.

The real PC2 Codex Desktop 0.160 conversation `01a10030-...` was re-run after
this promotion. At 2026-10-03 11:16:30 UTC the request still terminated as
`502 previous_response_owner_unavailable` on Beta, with `account_id=NULL` and
`http_bridge_routing stage=admission reason=smart_session`. This second product-
path result disqualifies `sha256:b57e00a8...` as the final Stage-1 image even
though its deployment/runtime qualification remained healthy.

Source review isolated the remaining bypass to the HTTP-bridge recovery gate.
The raw HTTP fallback had already adopted a strong native-recovery predicate,
but the bridge still required `not enforce_openai_sdk_contract` before allowing
the local recovery refusal. Codex Desktop 0.160 is a recognized first-party
native client while also being able to select the SDK-compatible public wire
contract, so the bridge skipped the native refusal and surfaced the legacy 502.

The follow-up correction introduces one shared `native_codex_recovery_contract`
predicate. Native identity remains required. When the public layer selected the
SDK-compatible wire contract, only a recognized native `originator` can retain
the native recovery contract; a User-Agent-only lookalike remains excluded. The
same predicate is now used by fresh durable reattach, explicit-anchor bridge
admission, and the raw-HTTP fallback.

Validation after this second product-path correction:

- owner-interruption suite: 33 PASS, including bridge enabled/disabled with and
  without SDK-compatible request metadata
- core native/SDK/bridge/ownership/source matrix: 1,276 PASS
- extended HTTP/native-egress/model-source routes: 355 PASS, 319 SKIP for the
  unconfigured external native-egress binary, 0 FAIL
- Ruff, format, targeted typing and `git diff --check`: PASS

The second product-path correction was committed as
`f0ac5a3f217d399e31b7b5a145b2b885facbecf7` and fast-forwarded locally into
`codex/main-d1fd-patch-packet-20260917`; no remote push was performed.

Before packaging, all three changed application files were compared between
parent source `9e2e7ada...` and the running production image
`sha256:b57e00a8...`; every SHA-256 matched. The new unpromoted candidate is:

- image:
  `sha256:8a59f62018a4f6209ed4aa5dcc517bea707fb5a223241b5aeeab12f4a6fe5612`
- revision:
  `f0ac5a3f217d399e31b7b5a145b2b885facbecf7`
- exact base:
  `sha256:b57e00a806013619d0c122a20ef28116b1c81ea3e3123226af1ecd51f053ab2e`
- scope label: `pc2-native-originator-recovery-reviewed`
- three-file bundle SHA-256:
  `ca963adf2ce8fac77fff4dd8dd621c7186c21969cc8f7bde7232b89bfe1573bc`
- `continuity.py`:
  `307e458b8ae50e2d5f5ef5e3be6ab1e5c36726c45673ded6629908edbc6c1ea8`
- HTTP-bridge `streaming.py`:
  `aaa65436adf2152ca3b68974b078ab8047d2181c8b63398a403c07fd7ab6eaa9`
- raw streaming `retry.py`:
  `b16b0fa093f3df24da0e2fbdfcd6d0fbbbce5aa1e1af7e72bbd39c5498ccbfe2`

All three source/image hashes match byte-for-byte. In-image smoke proved that
SDK-compatible wire selection plus a recognized native `originator` retains the
native recovery contract, while a User-Agent-only Codex lookalike and an ordinary
SDK do not. The same smoke reconfirmed HTTP 400 + `invalid_request_error` +
`continuity_recovery_required`, `x-should-retry:false`, and no Retry-After or
Retry-After-Ms.

After explicit authorization, `sha256:8a59f620...` was promoted to production
Beta with the same rollback-safe transaction pattern. The new running Beta is
container `db514103...` on image
`sha256:8a59f62018a4f6209ed4aa5dcc517bea707fb5a223241b5aeeab12f4a6fe5612`.
The predecessor `sha256:b57e00a8...` is retained stopped with `restart=no` as
container `40fce5b7...` under
`codex-lb-beta-pre-native-originator-recovery-20261003T115033Z-69592`.

Post-promotion qualification confirmed local and tailnet Beta/Stable readiness
HTTP 200, unchanged Stable and PostgreSQL identities, the expected revision/base/
scope/bundle labels, byte-for-byte runtime hashes for the three overlay files,
zero nonterminal operations, zero unexpired leases, unchanged PostgreSQL system
identifier/Alembic head, no actual startup/runtime error markers, and a released
recreation lock.

Stage 2 remains blocked on one final real PC2 retest of conversation
`01a10030-...` against this promoted candidate.

### Third actual PC2 Desktop retest: known explicit anchor owner

The real PC2 conversation was re-run after promotion of `sha256:8a59f620...`.
At 2026-10-03 11:55:31 UTC request
`8f866516-0fb2-4816-9477-1545a0608445` still returned
`502 previous_response_owner_unavailable` with `account_id=NULL`. The request
used API key `ee0a3000-...`; the latest successful response in the same
conversation had used API key `1c6c7caa-...` and account `_992e5245`.
The admission trace again showed `smart_session`, but that label is only the
transport-policy decision, not the error producer.

The remaining defect was deeper in HTTP-bridge owner recovery. Codex Desktop
0.160 sends an explicit `previous_response_id` on this continuation. Once owner
recovery advice confirmed the known owner remained unavailable beyond the bounded
short-hold window, `native_delta_requires_owner()` excluded the request because
that predicate intentionally required `payload.previous_response_id is None`.
The request therefore fell through to `_http_bridge_previous_response_owner_unavailable_error()`
and advertised another retryable-looking 502 even though repeating the same
explicit anchored delta could not make its owner portable.

The corrected boundary is now:

- recognized backend Codex session-affinity is mandatory;
- when the public layer selects an SDK-compatible wire contract, native identity
  requires either a recognized native originator or a native Codex User-Agent
  plus a stable backend thread/session identity;
- a native explicit-anchor **delta-only** continuation with a known unavailable
  owner becomes local `400 continuity_recovery_required` after the bounded
  short-hold window;
- the explicit anchor and owner proof are preserved; no cross-account dispatch
  occurs;
- verified full resend, file/account-bound, non-native, `/v1`, and ambiguous or
  post-dispatch cases retain their existing contracts.

Validation of this corrected tree:

- owner-interruption suite: 34 PASS
- core native/SDK/bridge/ownership/source matrix: 1,282 PASS
- extended HTTP/native-egress/model-source routes: 355 PASS, 319 SKIP for the
  unconfigured external native-egress binary, 0 FAIL
- Ruff, format, targeted typing, proxy architecture, cancellation-safety and
  `git diff --check`: PASS
- changed OpenSpec CI: 7 PASS
- strict changed-spec validation: PASS; complete OpenSpec validation: 156 PASS,
  0 FAIL

The correction was committed as
`6ff174e733871d3efefa53838a7c22c9b68031b7` and fast-forwarded locally into
`codex/main-d1fd-patch-packet-20260917`. The reviewed line, including candidate
evidence commit `59a61b37634d4a30cea73b3d11a4d09b0d0c19ee`, is also preserved on
XZ remote branch `codex/fix-pc2-owner-recovery-handshake-20261003`.

Before packaging, the three changed application files were compared between
parent source `515fb16a5...` and the running production image
`sha256:8a59f620...`; every SHA-256 matched. The new unpromoted candidate is:

- image:
  `sha256:291a47e3050852faa16fe4332515edd64e3012df033207db9d3af8e883bf9827`
- revision:
  `6ff174e733871d3efefa53838a7c22c9b68031b7`
- exact base:
  `sha256:8a59f62018a4f6209ed4aa5dcc517bea707fb5a223241b5aeeab12f4a6fe5612`
- scope label: `pc2-native-explicit-owner-recovery-reviewed`
- three-file bundle SHA-256:
  `55244fde2168623a6373b1857c289fd1e04017ef8e6b62e1f299436ccb950d1e`
- `continuity.py`:
  `ed06a87ab70d0061187f1659beaaaf75c23ec50872b2809f36870062871034ca`
- HTTP-bridge `streaming.py`:
  `8624f6046e995eca0039a95d6149c65e178df718700be35e6d083e83e791d428`
- raw streaming `retry.py`:
  `4241f533e9ec8fea91f3b93f9f10cc4d01761ac89c561e97df2f049a3cd2bd4b`

All three source/image hashes match byte-for-byte. In-image smoke reconfirmed
the strong native session-affinity boundary: native Codex UA plus real thread
identity qualifies even under SDK-compatible wire selection, whereas UA-only,
ordinary SDK, and non-session-affinity requests do not. The same smoke returned
HTTP 400 `continuity_recovery_required`, `x-should-retry:false`, and no
Retry-After / Retry-After-Ms.

The running production Beta remains the operationally healthy but Stage-1-
disqualified `sha256:8a59f620...` image. Candidate `sha256:291a47e3...` has not
been promoted and still requires a new explicit production-promotion approval.

A dedicated copy of the previously qualified rollback-safe Beta transaction was
prepared as `artifacts/pc2-owner-final-review-20261003/promote_beta_native_explicit_owner_recovery.py`.
Its read-only `check` action passed against the live topology immediately before
the approval gate: Beta container `db514103...` remained on `8a59f620...`, Stable
remained `0c717ce1...`, PostgreSQL remained `1e42fec6...` at Alembic head
`20260913_000000_add_oidc_provider_flow`, and both nonterminal operations and
unexpired session leases were zero. The script also pins candidate revision,
base, bundle and scope labels.

After explicit promotion authorization, the first `execute` attempt stopped
before any production mutation because Docker Desktop rendered one equivalent
macOS bind source as `/host_mnt/Users/...` on the predecessor and `/Users/...`
on the created candidate. The transaction equivalence gate was narrowed only to
canonicalize that Docker Desktop bind-source display prefix; mount target,
read-only mode, volume, port, environment, security and restart semantics stayed
strictly compared. The failed stopped candidate was removed and the transaction
was rerun from a fresh read-only preflight.

The successful promotion produced:

- running Beta container:
  `b114b792d8213b9b9434e3ec01b07af42c5471e4b35566329d2a3eda1be45c85`
- running image:
  `sha256:291a47e3050852faa16fe4332515edd64e3012df033207db9d3af8e883bf9827`
- retained predecessor:
  `db51410384999784431451aa457ce5dbda4d227c2a8847d0973d87918fe8780e`
  as `codex-lb-beta-pre-native-explicit-owner-recovery-20261003T124556Z-78862`,
  stopped with `restart=no`
- Stable unchanged as container `0c717ce1...` on `sha256:11eb4370...`
- PostgreSQL unchanged as `1e42fec6...`, system identifier
  `7684501606386458669`, Alembic head
  `20260913_000000_add_oidc_provider_flow`

Post-promotion qualification passed: local and tailnet Beta/Stable readiness are
HTTP 200, runtime configuration matches the predecessor apart from image/
provenance/restart state, all three overlay SHA-256 values match the reviewed
source/image evidence, nonterminal operations and unexpired leases are both zero,
there are no actual startup/runtime error markers, and the recreation lock is
absent.

The remaining Stage-1 gate is one real PC2 Codex Desktop 0.160 request on
conversation `01a10030-...` to prove that the formerly repeating explicit-anchor
owner-unavailable turn now terminates as local HTTP 400
`continuity_recovery_required` without upstream dispatch or a retry loop.

### Fourth actual PC2 retest: durable anchor survives but owner proof does not

The real PC2 conversation was re-run after promotion of `sha256:291a47e3...`.
At 2026-10-03 12:55:40 UTC request
`9a6d281b-936e-4985-a071-7219b621ec5c` still returned
`502 previous_response_owner_unavailable` with `account_id=NULL`. The public
request log retained the real Codex Desktop 0.160 thread id and the Beta API-key
scope. The API key itself has no account-assignment scope, so the result was not
caused by an operator restriction on alternate accounts.

Review of the admission path identified the remaining scope-loss shape: the
incoming native request can omit an explicit previous-response anchor while the
durable session lookup still injects its stored response id. After an API-key
identity change, that durable row can retain the anchor but expose `account_id`
as NULL in the current scope. `required_continuity_owner_missing` therefore
correctly fails closed, but the previous Stage-1 implementation only translated
the client-explicit owner-lookup miss; a proxy-injected durable anchor with the
same missing owner proof still fell through to the legacy 502.

The follow-up correction adds a narrow `native_missing_owner_requires_local_recovery`
gate at that pre-dispatch boundary. It requires native backend session affinity,
a stored response anchor, missing preferred owner proof, and—when the anchor was
injected by the bridge—an unsubmitted delta that is not a proved complete
account-neutral resend. It performs no cross-API-key owner lookup and creates no
upstream session. Existing client-explicit handling remains intact.

Validation of this scope-loss correction:

- core native/SDK/bridge/ownership/source matrix: 1,284 PASS, 0 FAIL/ERROR
- HTTP bridge + model-source extended matrix reached 343 PASS before one SQLite
  test setup failed because the host filesystem was full; that exact test was
  rerun alone after pressure subsided and PASSed
- Ruff, format, targeted typing, proxy architecture, cancellation-safety,
  changed-spec validation and `git diff --check`: PASS

The scope-loss correction was committed as
`28c0f34edf84bcda1187383873b6e1d0cd572e24` and fast-forwarded locally into
`codex/main-d1fd-patch-packet-20260917`; no new production promotion was
performed.

Before packaging, the only changed product file (`http_bridge/streaming.py`) was
compared between parent source `50032ef97...` and the running production image
`sha256:291a47e3...`; both SHA-256 values were
`8624f6046e995eca0039a95d6149c65e178df718700be35e6d083e83e791d428`.
The resulting minimal candidate is:

- image:
  `sha256:de38a1453e8a6589a99ef0056a91b64c46b1a0850fdb577ac109c9c7c399698b`
- revision:
  `28c0f34edf84bcda1187383873b6e1d0cd572e24`
- exact base:
  `sha256:291a47e3050852faa16fe4332515edd64e3012df033207db9d3af8e883bf9827`
- scope label: `pc2-durable-owner-proof-loss-reviewed`
- one-file bundle SHA-256:
  `85b7b15f1fce621dcd0912c8916082f1ef7a486da36e7a85d06ccb2d40716391`
- `http_bridge/streaming.py` source/image SHA-256:
  `99133af498020f42a395f0740c8f4dc7cd08d43eb860d4345ae8e84d43995ffb`

The source/image hash matches byte-for-byte. In-image code smoke verified the
scope-loss gate, the hashed `continuity_owner_proof_missing` refusal reason, the
local recovery raise, and absence of any cross-API-key lookup implementation in
the patched bridge method. The running production Beta remains
`sha256:291a47e3...`; candidate `sha256:de38a145...` is not promoted.

### Production follow-up: revoked access token is repeatedly reselected

Before promoting the durable owner-proof candidate, a separate real Beta canary
exposed an independent pre-dispatch authentication loop. Multiple consecutive
native requests selected the same prompt-cache account and failed opening the
upstream connection with structured error code `token_revoked`. Because the
error arrived as an upstream `ProxyResponseError` rather than the ordinary 401
branch, HTTP-bridge session creation surfaced it immediately and the account
remained eligible for the next request.

This failure is intentionally separated from the durable owner-proof repair. A
`REAUTH_REQUIRED` row is not by itself evidence that the currently stored access
token is unusable: refresh-token-only failures may leave a valid access token
that should keep serving traffic until expiry. The new boundary therefore uses
`token_revoked` as positive evidence about the current access token, permits one
forced refresh, and only then persists a revoked-access-token reauthentication
reason if the refreshed path still cannot authenticate. That reason is the
selector/owner-recovery proof used to keep the account out of subsequent
ordinary routing; other `REAUTH_REQUIRED` reasons retain their existing
warning-only behavior.

For soft prompt-cache/session affinity, a proven revoked account is excluded and
the current retry explicitly requests sticky reallocation. Hard continuity/file
ownership remains fail-closed and never becomes an implicit cross-account
continuation. This follow-up is being implemented and qualified in an isolated
branch; no production promotion is authorized by this section.

Implementation and qualification of this follow-up completed on an isolated
PC2 worktree based exactly on `e3384493761dca6552fd428d45ea9639f47422fd`.
The final implementation keeps `REAUTH_REQUIRED` warning-only semantics for a
usable access token, but adds `token_revoked` to the permanent reauthentication
codes and treats the corresponding persisted reason as proof that the current
access token is unusable. The same predicate is shared by ordinary selection and
owner-recovery advice. HTTP-bridge connection admission allows one forced
refresh; if the refreshed connection is still revoked, or that forced refresh
fails permanently, it persists the stronger revoked-access-token evidence. A
soft request excludes the account and explicitly reallocates sticky affinity;
a hard owner remains pinned and surfaces the authentication failure.

The initial implementation made `http_bridge/mixin.py` exceed its architecture
line budget. Auth retry classification and credential-failure recording were
therefore moved into the existing `proxy_failover.py` responsibility. The final
`mixin.py` is exactly 2,436 lines, equal to the architecture limit, and the proxy
architecture guard passes.

Final qualification evidence on the refactored tree:

- targeted revoked-token behavior: 7 PASS, plus the permanent-refresh-failure
  edge suite 4 PASS;
- selector/sticky/owner-recovery suites: 395 PASS;
- HTTP-bridge session-creation subset: 79 PASS;
- broad native/SDK/bridge/ownership/source matrix: 1,654 PASS, 0 FAIL;
- model-source plus HTTP Responses cross-route matrix: 683 PASS, 0 FAIL;
- Ruff and format: PASS; targeted `ty==0.0.78` on every changed application
  file: PASS;
- full `ty==0.0.78 app` still reports the same 9 diagnostics on both this tree
  and a clean `e33844937` comparison worktree, so the hotfix introduces no new
  whole-tree typing diagnostic;
- proxy architecture, cancellation-safety, and `git diff --check`: PASS;
- strict `replace-http-owner-recovery-handshake` validation and complete
  OpenSpec validation: 156 PASS, 0 FAIL.

No Stable/PostgreSQL lifecycle operation, product-schema migration, live DB
mutation, ProviderSwitcher installation, or Beta promotion was performed during
this qualification.
