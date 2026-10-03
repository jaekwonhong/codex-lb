## 1. Contract

- [x] 1.1 Record the production failure mode and the HTTP-only client limitation.
- [x] 1.2 Define the exact recovery-required boundary and retained fail-closed cases.

## 2. Implementation

- [x] 2.1 Add the explicit continuity-recovery-required error envelope.
- [x] 2.2 Replace only the quota-owner fresh-reattach client-history handshake.
- [x] 2.3 Remove the temporary native previous-response unmasking exception.
- [x] 2.4 Include the new failure in bridge preflight request-log attribution.

## 3. Verification

- [x] 3.1 Rerun unit regressions on the corrected native-only HTTP 400 contract.
- [x] 3.2 Rerun route-level no-dispatch, NULL-account logging and SDK boundary regressions.
- [x] 3.3 Rerun existing owner interruption, HTTP bridge replay, stale-anchor masking and model-source regressions.
- [x] 3.4 Rerun Ruff, format, targeted typing, diff check and strict OpenSpec validation.
- [x] 3.5 Execute the actual-SDK MockTransport retry regression and committed-native-SSE test.
- [ ] 3.6 Verify the actual PC2 Desktop failure lifecycle before any production qualification claim.

### Corrected-tree qualification

- Local-history/API unit contract: 40 PASS.
- Production-shape owner interruption route suite: 15 PASS.
- HTTP bridge owner/replay/reattach focused suite: 46 PASS; full-resend owner/replay/reattach integration subset: 25 PASS.
- Model-source WebSocket guard suite: 18 PASS.
- Changed proxy application files pass targeted `ty check`; Ruff, format and `git diff --check` pass.
- Strict OpenSpec change validation passes; main spec tree: 66 PASS, 0 FAIL.
- Proxy architecture and cancellation-safety guards pass.
- The official Python SDK MockTransport regression proves the corrected 400 path issues one request, while the superseded 409 fixture retries.
- Current public Codex source classifies HTTP 400 as terminal at the transport layer and `invalid_prompt` as a terminal `response.failed` category; unknown failed-event codes are retryable. The committed-SSE compatibility surrogate is intentionally limited to the native local refusal.
- Actual PC2 Desktop behavior remains a production-path gate; these tests do not claim it has already been exercised.

## 4. Deployment

- [x] 4.0 Build a non-promotable review image from the exact current production
  Beta base and verify source/image hashes plus the JSON/SSE contracts in-image.
- [x] 4.1 After explicit commit/integration authorization, rebuild a
  commit-addressable minimal Beta derivative from the corrected source.
- [ ] 4.2 After explicit production-promotion authorization, preserve the rollback
  container, wait for a safe cutover boundary, replace Beta, and verify readiness;
  leave Stable untouched.

The previously built image `sha256:a0a5b6769775f740d289bbac3a087fe403b92bb0fc8efa478357a64aa6439d5c`
contains the reviewed 409 behavior, not these corrections. It is not the corrected
deployment candidate. The initial corrected edits were committed as `271b5354d`
and fast-forwarded locally, without push or deployment. Their image `f51b1047...`
was subsequently disqualified by the pre-promotion review in section 6 and MUST
NOT be promoted. A replacement must include the additional reviewed corrections.

Review image (not approved for promotion):

- image: `sha256:87b15bc98ad4db0b7407d0f4f00fc1a494124725d0adf261a02cd1d914feca6b`
- exact production base: `sha256:8d606b5add93fd526a3e7a2af4c56ac2dd7c176f74a1e67c316e9069ce2c8c48`
- source base: `ab78561f108cd60fffced3ecd170e4b02d50375d`
- uncommitted application diff SHA-256:
  `958ba54c7a01bfb85641ba280b3e043a36ed9686f994480784e6d84ae79e0152`
- all three copied application-file SHA-256 values match between the worktree and image.
- in-image smoke: pre-commit JSON is HTTP 400 + `continuity_recovery_required`
  + `x-should-retry:false` with no Retry-After; committed native SSE is terminal
  `invalid_prompt` with `availability_reason=continuity_recovery_required` and no
  SSE retry directive.

## 5. Review corrections

- [x] 5.1 Replace retry-prone 409/server_error with distinct 400/invalid_request_error.
- [x] 5.2 Generate no-retry headers only for the local refusal; remove conflicting JSON/SSE retry hints.
- [x] 5.3 Restrict the branch to native identity plus native backend SSE contract.
- [x] 5.4 Require local pre-dispatch provenance before NULL-account preflight logging.
- [x] 5.5 Preserve the original thread and describe owner recovery as an alternative to local-history fork.
- [x] 5.6 Add regressions for SDK retries, contract boundaries, provenance and committed SSE.
- [x] 5.7 Make an already-committed native SSE refusal terminal to Codex by using
  the `invalid_prompt` wire surrogate while retaining the real continuity marker.

## 6. Pre-promotion review of 271b5354d

- [x] 6.1 Reproduce and close native delta retirement after an advisory timeout or late owner rejection; retain SDK and verified full-resend contracts.
- [x] 6.2 Preserve thread attribution for native originator identity without a Codex User-Agent.
- [x] 6.3 Verify the preflight log persistence boundary with a delayed/failing store and bounded acknowledgement; preserve cancellation cleanup.
- [x] 6.4 Rerun native/SDK, ownership, replay, source-routing, static and OpenSpec regressions; keep production unchanged.

Pre-promotion corrected source: 1,271 core tests + 355 extended-route tests PASS.
The additional native-egress wire suite has 319 SKIPs due to its unconfigured
external binary; these are not product-path qualification. Ruff/format/typing,
architecture, cancellation-safety, diff and OpenSpec (66 specs) all pass.
Promotion and actual PC2 Desktop qualification remain unchecked in sections 3/4.

- [ ] 6.5 Commit/integrate the additional reviewed correction and rebuild/verify the four-file derivative. The earlier `f51b1047...` image is disqualified and MUST NOT be reused.
