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
- [x] 3.6 Exercise the actual PC2 Desktop failure lifecycle and record the residual explicit-anchor owner-proof-loss defect in the first promoted candidate.

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
- [x] 4.2 After explicit production-promotion authorization, preserve the rollback
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
The first production promotion completed, but actual PC2 Desktop 0.160 validation
found a residual explicit-`previous_response_id` owner-lookup-miss path. Therefore
image `sha256:c3fdb1b9...` is operationally healthy but does **not** satisfy the
final Stage-1 product-path qualification.

- [x] 6.5 Commit/integrate the additional reviewed correction and rebuild/verify the four-file derivative. Replacement commit: `aa059dea8`; image: `sha256:c3fdb1b9...`. The earlier `f51b1047...` image remains disqualified and MUST NOT be reused.

## 7. Production promotion evidence

- [x] 7.1 Promote only Beta to `sha256:c3fdb1b9...` after an idle durable-state gate; keep Stable and PostgreSQL identities unchanged.
- [x] 7.2 Retain predecessor `0d90b2bb...` stopped with `restart=no` for rollback.
- [x] 7.3 Verify local and tailnet readiness, exact four-file runtime hashes, PostgreSQL identity/head, zero startup/runtime error markers, zero nonterminal operations, and zero unexpired leases.
- [x] 7.4 Remove the two non-qualifying synthetic canary sessions/aliases after proving they owned no operation or recovery-attempt rows; restart Beta only and re-run the post-promotion qualifier.
- [ ] 7.5 Exercise the intended failure lifecycle from the actual PC2 Codex Desktop using its real process-session identity; synthetic HTTP calls do not satisfy this gate.

## 8. Actual PC2 Desktop 0.160 follow-up

- [x] 8.1 Capture the real PC2 failure on conversation `01a10030-...`: native Desktop 0.160 returned `502 previous_response_owner_unavailable` before dispatch.
- [x] 8.2 Prove the prior successful response and failing request used different proxy API-key ids, so current-scope owner lookup correctly refused to cross the API-key boundary.
- [x] 8.3 Extend the native backend contract so an explicit previous-response owner-proof miss returns the same local `400 continuity_recovery_required` refusal in both bridge and raw-HTTP paths; leave SDK behavior unchanged.
- [x] 8.4 Add Codex Desktop 0.160 route regressions for bridge enabled/disabled and an SDK boundary regression.
- [x] 8.5 Rerun owner-interruption, core, extended-route, Ruff, format, typing,
  architecture, cancellation, diff and OpenSpec checks: owner suite 31 PASS;
  core matrix 1,274 PASS; extended routes 355 PASS + 319 external-binary SKIPs;
  complete OpenSpec validation 156 PASS, 0 FAIL.
- [x] 8.6 Commit/integrate the follow-up source correction and build a new
  commit-addressable Beta derivative: commit `677128a72`, image
  `sha256:b57e00a8...`, exact base `sha256:c3fdb1b9...`; source/image hashes and
  in-image 400/no-retry contract verified.
- [x] 8.7 Promote `sha256:b57e00a8...` after separate authorization and re-run
  the same actual PC2 Desktop thread path. The real 0.160 request still returned
  `502 previous_response_owner_unavailable`, so this image is disqualified as
  the final Stage-1 candidate.
- [x] 8.8 Replace the bridge's remaining `not enforce_openai_sdk_contract`
  native gate with the shared strong-originator recovery predicate; preserve the
  SDK and User-Agent-only boundaries. Owner suite 33 PASS; core matrix 1,276
  PASS; extended routes 355 PASS + 319 external-binary SKIPs.
- [x] 8.9 Commit/integrate this second product-path correction and build a new
  commit-addressable Beta derivative from the exact running `b57e00a8...` base:
  commit `f0ac5a3f2`, image `sha256:8a59f620...`, three-file source/image hashes
  and in-image native-originator/SDK boundary smoke verified.
- [ ] 8.10 After separate production-promotion authorization, promote that new
  derivative and re-run `01a10030-...` one final time from the real PC2 Desktop.
  Promotion to `sha256:8a59f620...` is complete and post-promotion qualification
  passed, but the real PC2 retest returned `502 previous_response_owner_unavailable`;
  this candidate is therefore disqualified as the final Stage-1 image.

## 9. Known explicit-anchor owner follow-up

- [x] 9.1 Capture the third real PC2 failure on `01a10030-...`: request
  `8f866516-...` returned 502 after promotion of `8a59f620...`.
- [x] 9.2 Trace the failure to the owner-recovery advice branch: the native
  delta predicate excluded client-supplied `previous_response_id`, so a known
  unavailable owner fell through to the legacy 502.
- [x] 9.3 Extend strong native identity to backend session-affinity requests that
  use native Codex UA plus stable thread/session identity when originator is
  absent; keep `/v1`, ordinary SDK, and turn-state-only requests excluded.
- [x] 9.4 Make native explicit-anchor delta-only turns return the same local
  recovery-required refusal after the bounded short-hold window while preserving
  verified full-resend, file-bound, non-native, and ambiguous-dispatch behavior.
- [x] 9.5 Add/adjust regressions for Desktop 0.160 explicit-anchor delta-only,
  strong-identity boundaries, and backend SDK-compatible wire selection.
- [x] 9.6 Rerun qualification: owner suite 34 PASS; core 1,282 PASS; extended
  routes 355 PASS + 319 external-binary SKIPs; Ruff/format/typing/architecture/
  cancellation/diff PASS; OpenSpec 156/156 PASS.
- [x] 9.7 Commit/integrate this correction and build a new minimal derivative
  from the exact running `8a59f620...` production base: commit `6ff174e73`,
  candidate `sha256:291a47e3...`, exact-base/source/image hashes and in-image
  native session-affinity/400-no-retry smoke verified. Preserve the reviewed
  line on XZ remote branch `codex/fix-pc2-owner-recovery-handshake-20261003`;
  read-only promotion preflight reports ready with zero durable operations/leases.
- [ ] 9.8 After a new explicit promotion approval, promote that derivative and
  re-run the real PC2 conversation once more before closing Stage 1. Promotion
  to `sha256:291a47e3...` is complete and post-promotion qualification passed;
  the real PC2 retest still returned `502 previous_response_owner_unavailable`,
  so this image is disqualified as the final Stage-1 image.

## 10. Durable owner-proof scope-loss follow-up

- [x] 10.1 Capture the fourth real PC2 failure on `01a10030-...`: request
  `9a6d281b-...` returned 502 after promotion of `291a47e3...`.
- [x] 10.2 Confirm the current Beta API key has no account-assignment scope and
  the failure is therefore not an operator-created no-alternate restriction.
- [x] 10.3 Trace the remaining gap to a durable session anchor whose response id
  survives while current-scope `account_id` owner proof is absent.
- [x] 10.4 Extend the native pre-dispatch recovery refusal to that injected-anchor
  owner-proof-loss shape without widening cross-API-key lookup, verified full
  resend, SDK, `/v1`, file-bound, or post-dispatch behavior.
- [x] 10.5 Add native session-anchor owner-proof-loss regressions with and without
  SDK-compatible request metadata.
- [x] 10.6 Requalify: core 1,284 PASS; affected extended tests PASS (one full-run
  setup was interrupted only by host disk-full and passed alone on rerun);
  Ruff/format/typing/architecture/cancellation/change validation PASS.
- [ ] 10.7 Commit/integrate the scope-loss correction and build a minimal
  derivative from exact running `291a47e3...` production base.
- [ ] 10.8 After separate promotion authorization, promote that derivative and
  re-run the real PC2 thread before Stage-1 closeout.
