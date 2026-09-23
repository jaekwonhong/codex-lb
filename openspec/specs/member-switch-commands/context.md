# Current source and last admitted OFF release

The last admitted deployment is the [2026-09-20 Beta-only optional-5H OFF release](off-deployment-20260920.md): image `b98fe0f7…`, deployed source manifest `e55b3132…`, with immediate c409 predecessor `817ca6d0…` retained fenced. The release-specific `current_operations.py check` is read-only; older c409 `current_ops.py` recreation tools are not admission for b98. No fresh production health observation is claimed by these source notes.

The subsequent `rotation-epic-review-corrections` work changes source and tests only. Its local qualification does not replace the deployed b98 image or confer activation authority. Q3 remains **NOT RUN / NOT ADMITTED**. Historical checkpoint statements below describe their original dates, not the current release or correction status.

# Dispatch evidence

Automatic dispatch reuses the durable member-switch child and its post-claim
hook. Weekly eligibility can expire while catalog, preview, admission, or quota
calls wait, so the same decision receipt is assessed again at the last local
boundary before the Companion start call. A pre-dispatch rejection closes only
a proven local non-effect and preserves outgoing Usage snapshots.

The qualified Companion publishes outgoing identity before DELETE. That
identity is therefore an intended target, not a success acknowledgement. Only
the post-verification outgoing-absence trace can confirm removal; absent or
truncated proof keeps the effect unknown and reserved even outside the rolling
quota windows. For example, a failed deletion naming the exact outgoing member
still occupies a quota slot after eight days until authoritative reconciliation.

See [the qualified correction and remaining Q3 work](../../changes/archive/2026-09-17-rotation-dispatch-evidence/context.md).
Backend dispatch evidence validation does not establish runtime provenance;
the subsequent Companion-side canary gate work is described below.

# Canary execution and managed delete telemetry

The source candidate `2.11.48-canary.1` implements a durable one-workflow budget
with one persisted claim per DELETE and invite. The dedicated managed
`/canary-operations` endpoint requires explicit canary mode; a rejected endpoint
never falls back to manual execution. The outgoing member must be authoritatively
absent before invite admission. Canary also disables the manual verifier's
`404/member_identity_missing` DELETE retry. Reconstructed stores never grant a
fresh effect claim, including an unused invite claim.

Managed removal observations retain sanitized JSON types and capture uncertainty
separately from invitation telemetry. Subsequent operation updates and restart
preserve those observations.

The first canary binding advances the receipt store to schema 2. Older runtimes
reject that store; preserve it during rollback rather than restoring a pre-canary
copy or deleting it. The budget is bounded by the lifetime of this retained store.

At the original candidate checkpoint, local tests and independent review were
complete but deployment was still pending. The 2026-09-19 matched OFF deployment
subsequently provisioned this Companion; later Beta-only replacement retained it.
See [candidate provenance, verification,
examples and rollback constraints](../../changes/archive/2026-09-17-companion-canary-effect-boundaries/context.md).

# Current host attestation and bounded scheduling

The subsequent source change wires a default-off, single-evaluation scheduler
into application startup/shutdown and connects P1/P2/P3/P5. It requires an
operator plan plus enabled workspace intent and externally signed, expiring host
evidence. It rechecks plan expiry/revocation after the final awaited intent read,
then Weekly evidence and runtime signature immediately before Canary start.

The external macOS verifier matches listener PID/start and mapped executable
device/inode, computes the binary hash and checks identity/metadata again. A raw
Ed25519 public key is the operator-provisioned backend trust root; the private
key remains with the verifier. Receipts last at most 30 seconds and bind the
configured endpoint and qualified release tuple. This bounds staleness; it does
not lock the host process across the network call.

The retained `rotation-q3-single-evaluation` control record admits only one
evaluation. A legitimate reset recovery closes without removal or quota; an
interruption before controller creation stays blocked rather than repeating a
reset. Existing controllers reconcile without a new evaluation. Keep the record,
quota state and Companion receipts through rollback. The source change does not
install keys, enable plans or qualify the newer Companion artifact. See
[runtime contracts, evidence and remaining release work](../../changes/archive/2026-09-18-rotation-runtime-dispatch/context.md).

The [2026-09-18 artifact build qualification](build-qualification-20260918.md)
records reproducible Companion binaries and an isolated backend image with OFF
startup checks. It also records production baseline drift; these historical-base
artifacts are not admitted for replacement of the newer production lanes.

# Current baseline and artifact registration

The [2026-09-19 reconciliation](../../changes/archive/2026-09-19-rotation-current-artifact/context.md)
rebases the rotation delta on current Beta `62cd34ce`, registers the exact
reproducible Companion binary and source manifest without an owning commit,
and verifies signed synthetic dispatch and restart safety. Artifact registration
was locally qualified at that checkpoint. Matched OFF deployment followed;
Q3 live-canary admission remains separate and has not been performed.

## Matched OFF deployment and Q4 decision

See [2026-09-19 deployment and decision](off-deployment-20260919.md) for the historical c409 matched pair, installed signer and Q4 NO-GO / KEEP OFF result. That day's preflight rejected missing 5H input. The subsequent [b98 OFF release](off-deployment-20260920.md) supports explicit same-fetch 5H absence; it is not a new Q3 preflight or canary approval.

## Non-canary follow-up

[2026-09-19 diagnostic results](noncanary-diagnostics-20260919.md) record the explicit no-live-canary scope: upstream Weekly-only input, 28/29 independent checks passing, preserved state and no activation authority.


# Optional 5H response evidence

The [2026-09-19 optional 5H source qualification](optional-five-hour-20260919.md)
permits Weekly-only retention only with explicit same-fetch absence provenance,
preserves legacy incomplete-history rejection, and distinguishes 미제공 from 미확인.
This capability and its P2 corrections were subsequently deployed in the
2026-09-20 b98 Beta OFF release. Its exact source identity remains e55; later
source edits are not silently attributed to that deployed manifest.

The [P2 compatibility and uncertainty corrections](optional-five-hour-p2-fixes-20260919.md)
restore opaque JSON complete-pair recovery and distinguish retained raw unknown
5H values from validated history. Prior sealed HOLD evidence remains unchanged;
the correction packet separately records the new source and OFF artifact decision.

## Review corrections and interrupted evaluation

The 2026-09-20 source review identified final reset-admission, committed intent response,
pre-start recovery and scheduler-test gaps; later independent evidence added an
operator wire-alias mismatch. The follow-up source change is
`rotation-epic-review-corrections`; it is not a production release.

For a valid existing plan, interrupted work before the member-switch start claim
now becomes `needs_attention` with `rotation_prestart_interrupted_requires_attention`.
Its original G1 classification remains historical evidence, not renewed eligibility.
The binding, snapshot rows, child ownership and quota remain retained. For example,
a snapshot/preview crash must not be retried with a new evaluation UUID or by
deleting its fixed binding. Review the durable controller/child/quota evidence and
use a separately qualified recovery procedure; there is no automatic reset/start
retry or operator effect-replay button. Already-claimed effects retain their
existing reconciliation path rather than being recategorized as non-effects.
