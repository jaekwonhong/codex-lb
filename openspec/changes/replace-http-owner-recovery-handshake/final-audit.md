# Final pre-promotion audit (2026-10-03, completed 2026-10-04)

## Authority and frozen baseline

The user requested a final review to prevent repeated defects, errors and blocked
validation. This audit may correct code and tests locally. It does not authorize
another production promotion, remote push, production database mutation, account
fault injection, Stable changes, or a persistent watcher.

Reviewed source starts at `e3384493761dca6552fd428d45ea9639f47422fd`, including
product commit `28c0f34edf84bcda1187383873b6e1d0cd572e24`. At the audit closeout
boundary, Production Beta was
`sha256:291a47e3050852faa16fe4332515edd64e3012df033207db9d3af8e883bf9827`.
An all-tracked-Python SHA comparison at that boundary covered the tracked
application Python set and isolated the intended audit delta. The audit uses its
own worktree to avoid concurrent edits to the previous candidate.

Before integration began on 2026-10-04, a separate already-completed
`preferred-owner-token-failover` promotion changed the live Beta to container
`e0e2872679beb6ed367c6edbbc0fb51575efefea2fc3b1226ccdd1285579a087`,
image
`sha256:15e9982c05d4f974629d53fb04fffc95a06990e9b484c08139093e0087af3cbf`.
That image records
`codex-lb.patch.base-image=sha256:291a47e3050852faa16fe4332515edd64e3012df033207db9d3af8e883bf9827`
and revision `4d05b1e6a483abe0394663b16262d76adb803c3a`. This audit did not
perform that promotion. A direct live-image comparison shows that the two files
modified by this audit differ from the new live image only by the audit hunks
documented below, so the later failover work can be preserved by deriving the
Stage-1 candidate from the current live image rather than reverting to the old
291a base.

## Evidence correction

The observed PC2 request `9a6d281b-936e-4985-a071-7219b621ec5c` returned 502,
`previous_response_owner_unavailable`, and NULL request-log account attribution.
Those facts do not prove that the request omitted an explicit anchor, that a
durable lookup returned a NULL owner, or that SDK metadata was present. A NULL
preflight attribution means no account was attributed to that log row, not that
every owner lookup was NULL. Earlier root-cause statements beyond these observed
facts are hypotheses until an exact request-shape / routing-state reproduction
supports them.

The coordinator filters entire alias/session lookups by API-key scope. It does
not redact just `account_id` from a foreign-scope row. Its retirement projection
clears the response anchor together with the owner. The mocked NULL-owner,
non-NULL-anchor fixture covers an inconsistent/legacy-state defense, but does
not by itself prove cross-scope runtime behavior.

## Review tasks

- [x] Freeze source and record live runtime identity without mutation.
- [x] Reproduce native raw owner-proof loss with zero-, one-, and two-account pools.
- [x] Reproduce explicit-anchor owner rejection after advisory timeout / miss.
- [x] Verify injected-anchor and explicit-anchor file / dispatch / SDK boundaries.
- [x] Verify committed-SSE error delivery with SDK-compatible native wire mode.
- [x] Re-run core tests serially with execution-local reports and source hashes.
- [x] Record remaining product-path and operational promotion blockers honestly.

## Defects found and corrected locally

### Raw HTTP account cardinality was incorrectly acting as owner proof

The raw HTTP continuation path resolved an explicit `previous_response_id` owner
first. When that lookup returned NULL, it loaded the selectable account pool and
only emitted the owner-unavailable/recovery contract when the pool size was not
exactly one. A one-account pool is not evidence that the remaining account owns
the stored response. For native Codex this could therefore bypass the terminal
local-history refusal solely because one selectable account happened to remain.

The audit moves the native `continuity_recovery_required` refusal ahead of pool
inspection. SDK/non-native requests retain the prior compatibility behavior.
Regression coverage pins native pool sizes 0, 1, and 2 and asserts that neither
account selection nor upstream session creation is reached.

### Late explicit-anchor owner rejection could bypass the early recovery contract

The bridge already refused a native explicit anchored delta when an early owner
advisory proved the owner unavailable. If that advisory timed out or returned no
result, however, session admission could later return
`previous_response_owner_unavailable`. The late guard only covered the
bridge-injected-anchor delta predicate, allowing the client-explicit anchor to
fall through toward legacy owner retirement/retry behavior.

The audit now treats a confirmed pre-dispatch owner rejection for a native
client-explicit anchored delta as terminal immediately after any bounded wait.
It returns the same local recovery refusal without clearing the anchor, retiring
the continuity owner, selecting another account, or requiring the optional
advisory lookup to prove an alternate. Synthetic admission-failure tests cover
both advisory miss and advisory timeout and assert a single session-creation
attempt, no owner retirement, and no second upstream dispatch.

### Promotion transaction state flags could make cleanup ambiguous after I/O failure

The local Beta promotion artifact set `predecessor_touched=True` before the
pre-mutation journal write and set `committed=True` before the final committed
journal plus recreation-lock release. A filesystem/journal failure at either
boundary could therefore make exception cleanup believe a side effect had
already occurred, or suppress cleanup even though final durable evidence/lock
release had failed.

The transaction now records the pre-mutation journal before marking the
predecessor touched, and records the final journal plus releases the lock before
marking the promotion committed. If rollback is proven but recreation-lock
release itself fails, the original promotion failure remains authoritative and
the script attempts to leave a `needs-review` marker; if even that marker cannot
be written, the residual lock directory remains as a fail-closed fence.

An initial in-memory Docker/runtime fault matrix then exposed one more P0 in the
rollback implementation itself: rollback tried to inspect/clean the candidate
before restoring the predecessor. A synthetic candidate-start failure followed
by candidate-inspect failure reproduced the dangerous state exactly: the old
Beta remained stopped under its backup name while the stopped candidate still
owned `codex-lb-beta`, leaving the service unavailable behind a `needs-review`
lock.

Rollback is now service-restoration-first. It resolves the canonical Beta-name
occupant by container id, fences/stops/renames the candidate when necessary
without requiring candidate inspection, restores and starts the predecessor,
proves readiness and exact predecessor identity/restart policy, and only then
does non-critical leftover-candidate housekeeping. A failure to prove that
housekeeping no longer undoes the restored service; it retains the recreation
lock plus `needs-review` for an operator instead.

The v3 fault matrix exercises journal failure before the fence, journal failure
before candidate start, final journal failure, transient and persistent final
lock-release failure, candidate-start plus candidate-inspect failure, and the
success path. All failure cases restore the exact predecessor running with its
original restart policy. Recoverable failures leave no lock; unresolved cleanup
retains lock + `needs-review`; success leaves the candidate running, predecessor
stopped/fenced, and no lock. Result: `PROMOTION_FAULT_MATRIX_V3=PASS`. A separate
owner-file write fault also verifies that a lock directory newly created by
`acquire_lock()` is removed when lock ownership cannot be recorded.

## Final validation evidence

- Targeted raw-owner/late-explicit regressions: 14 PASS.
- Full owner-interruption suite after all audit test additions: 47 PASS.
- Final core matrix report
  `/tmp/pc2-owner-final-audit-core-final-20261004.xml`: 1,295 PASS,
  0 FAIL, 0 ERROR, 0 SKIP.
- Extended route report `/tmp/pc2-owner-final-audit-routes-20261004.xml`:
  355 PASS, 319 SKIP, 0 FAIL, 0 ERROR. All 319 SKIPs are the existing native
  SSE wire probes gated by unconfigured `CODEX_LB_NATIVE_EGRESS_TEST_BINARY`.
- Committed-response SSE refusal, with and without SDK-compatible Stainless
  metadata: 2 PASS; both retain the terminal native no-retry wire contract.
- Ruff check: PASS. Ruff format check: PASS after one mechanical reformat.
- Targeted `ty`: PASS.
- Proxy architecture: PASS.
- Cancellation safety: PASS.
- Changed OpenSpec CI: 7 PASS.
- Strict changed-spec validation: PASS.
- Complete OpenSpec validation: 156 PASS, 0 FAIL.
- `git diff --check`: PASS.
- Promotion script `py_compile`: PASS.
- Promotion script read-only `check`: PASS with zero nonterminal operations and
  zero unexpired leases. This does **not** authorize or execute a promotion.
- Promotion transaction fault matrix v3: PASS, including the reproduced
  candidate-start + candidate-inspect failure that previously stranded the old
  Beta stopped.

## Integration candidate evidence (2026-10-04)

The reviewed audit delta was committed as
`b0629e4ffb07f1a0d4fcdc59b125f572d4c0a784` and the canonical local
`codex/main-d1fd-patch-packet-20260917` branch was advanced to that commit by
fast-forward only. No remote push was performed.

Because Production Beta had already moved after the original audit closeout, the
new Stage-1 candidate was derived from the actual live predecessor
`sha256:15e9982c05d4f974629d53fb04fffc95a06990e9b484c08139093e0087af3cbf`
rather than the older 291a image. The target-file parent bytes at
`e3384493761dca6552fd428d45ea9639f47422fd` exactly match the live 15e base
for both audit files, proving that overlaying the audit commit does not overwrite
later changes in those files.

The resulting unpromoted candidate is:

- image:
  `sha256:372f32388f90d94180081227840b9cc4d0a55e5570c527285a364bb3df65f399`;
- revision label:
  `b0629e4ffb07f1a0d4fcdc59b125f572d4c0a784`;
- exact base label:
  `sha256:15e9982c05d4f974629d53fb04fffc95a06990e9b484c08139093e0087af3cbf`;
- patch scope: `pc2-owner-continuity-stage1-final-audit`;
- bundle SHA-256:
  `0bb99f78c531ba9020d0d2b4ec9421fc2fd19bb78aa01e37b338f421e1deb11d`.

Candidate/base byte comparison across all 752 tracked `app/**/*.py` files
shows exactly two changed paths and no others:

- `app/modules/proxy/_service/http_bridge/streaming.py`;
- `app/modules/proxy/_service/streaming/retry.py`.

Candidate/canonical-source comparison has five expected inherited differences,
all belonging to the separately promoted preferred-owner-token product commit
`4d05b1e6a483abe0394663b16262d76adb803c3a`:

- `app/core/balancer/__init__.py`;
- `app/core/balancer/logic.py`;
- `app/modules/proxy/_service/http_bridge/mixin.py`;
- `app/modules/proxy/_service/http_bridge/proxy_failover.py`;
- `app/modules/proxy/owner_recovery.py`.

Those five candidate bytes exactly match the 4d05 source worktree, while the
other 747 tracked application Python files exactly match the canonical b062
source. This closes the composite source-to-image byte provenance without
pretending the later preferred-owner-token commit is part of the b062 branch.

The candidate image preserves `Env`, entrypoint, command, user, working
directory, healthcheck, exposed ports, stop signal and image volume metadata
from the 15e base. The only image-config label differences are the four explicit
provenance labels above. Candidate-internal native recovery contract smoke is
PASS, and the relevant route regression subset is 16 PASS / 31 deselected,
including raw owner-lookup loss, late explicit-anchor admission failure, and
committed recovery refusal delivery.

No Production promotion was performed while creating or validating this
candidate.

The previous unrelated Windows mirror run had one real-clock one-second timeout
in an eventless bridge-reader test; the exact test passed three consecutive
isolated reruns. The authoritative Mac final core run above passed that test as
part of the complete 1,295-test matrix, so it is not an unresolved product
failure.

## Remaining gates and non-actions

A final tracked-Python source/image comparison after all audit edits covered 752
`app/**/*.py` files. There were no missing image files and exactly two source /
production differences, both intentional audit fixes:

- `app/modules/proxy/_service/http_bridge/streaming.py`
- `app/modules/proxy/_service/streaming/retry.py`

No other tracked application Python file differs from the currently running Beta
image, which rules out an accidental broad source drift in the proposed product
delta.

Production was not changed by this audit. At the original audit closeout,
before the later separate preferred-owner-token failover promotion, it was:

- Beta container `b114b792...`, image `sha256:291a47e3...`, running with
  `restart=unless-stopped`;
- Stable container `0c717ce1...`, image `sha256:11eb4370...`, running;
- PostgreSQL container `1e42fec6...`, healthy on its existing image.

At integration preflight on 2026-10-04 the current live state is:

- Beta container `e0e2872679be...`, image `sha256:15e9982c...`, running
  with `restart=unless-stopped`;
- Stable container `0c717ce1...`, image `sha256:11eb4370...`, unchanged and
  running;
- PostgreSQL container `1e42fec6...`, unchanged and healthy.

Therefore any new Stage-1 derivative built after this point must use
`sha256:15e9982c...` as its exact runtime base and overlay only the reviewed
audit delta. Building again from `sha256:291a47e3...` would discard the later
preferred-owner-token failover changes and is not acceptable.

Candidate `sha256:de38a145...` predates the two additional product corrections
found by this audit and MUST NOT be promoted as the final Stage-1 candidate.
The audit worktree is intentionally uncommitted and no new commit-addressable
image has been built. A later explicit integration request must first produce a
new derivative containing these audit fixes; production promotion remains a
separate approval boundary. After that promotion, one real PC2 product-path
request on `01a10030-...` is still required before Stage 1 can be closed.

No remote push, production DB mutation, account fault injection, Stable change,
or production promotion was performed during this audit.

## Validation rules

Tests use synthetic accounts and isolated test storage, never the production DB.
Keep a unique report per execution; a rerun cannot erase an earlier failing run.
Do not call helper-only smoke a product-path qualification. Do not aggregate an
interrupted run plus a single rerun as a clean full run. No new candidate may be
called production-ready solely because this test matrix passes.

Host disk space at audit start was about 1.3 GiB; before the final Mac matrices
it had recovered to roughly 3.5 GiB and was about 3.7 GiB at final closeout. The
filesystem remains 99% utilized, so low free space is still an operational risk
even though the final core and extended runs completed without disk-full errors.
Worker delegation was unavailable due missing exact chat identity; this audit
makes no claim of independent worker review.
