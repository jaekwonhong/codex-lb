# Current Beta reconciliation — 2026-09-19

The detached source starts at observed Beta source
`62cd34ce4f02e95b7cc5d950d78ab42a7416b822`. The prior verified rotation
patch applies without conflicts. Subsequent authentication, usage refresh,
source routing and proxy fixes remain intact. This is a targeted rotation
reconciliation against current Beta, not a new official Stable qualification.

| Behavior or assumption | Decision | Evidence / remaining invariant |
| --- | --- | --- |
| Fresh Weekly evidence, serialized reset resolution, durable quota/history | KEEP | Current baseline does not replace the verified dispatch-time freshness/non-effect corrections. |
| Authoritative removal evidence and managed typed telemetry | KEEP | Target identity alone cannot prove removal; sanitized DELETE observations must survive restart. |
| Companion canary effect claims and no replay | KEEP | Dedicated endpoint, retained one-workflow budget and remove-before-invite remain required. |
| Runtime host attestation and bounded scheduler | KEEP | No current baseline equivalent; default OFF, exact identity and short-lived signature remain mandatory. |
| Current auth/usage/model-source/proxy fixes | KEEP | Apply rotation to current HEAD; combined Beta packet and rotation qualification pass. |
| Historical build/release assumptions | REDUCE | Rebase source on current Beta and bind the new artifact to its actual source manifest. |
| Historical 4acf backend as replacement image | DROP | Would regress newer production fixes; retained only as historical evidence. |
| Historical P4 owning commit as new candidate identity | DROP | The new source is uncommitted and has a distinct executable/source identity. |

The registered Companion version is `2.11.48-canary.1`; executable SHA-256 is
`1ec90e2b7315a9a19d718b03ff7c8ec54e90ff72aa9ca92b83a060fe0456b2d1` and
canonical source manifest SHA-256 is
`b6f6c753595bbc09afcfb267e1d3a3660bf6fe54cb105b931095b4a19e6ef6e8`.
The manifest digest is SHA-256 of the sorted file-hash JSON object serialized
with separators `(',', ':')`. Exact binary and source hashes were rechecked
against the reproducible build packet. No owning Git commit is asserted.
For example, the correct binary with the historical P4 commit is rejected.
Legacy signed observations retain their canonical bytes by omitting absent
optional provenance fields. The new source digest is covered by the signature.

Qualification includes the current Beta packet (170 unit + 8 integration tests)
and rotation suite (363 tests), Ruff and ty. New regression cases verify signed
current-artifact dispatch, altered/missing identity rejection, legacy signature
compatibility and controller restart without duplicate start. These use a fake
Companion and temporary database; they are not live cross-process canary proof.

Base image inspection additionally found three qualification-script differences
from labeled HEAD: the candidate gate lacks a mount-identity check and the Beta
packet scripts lack expanded WebSocket/DGX checks. Their exact image hashes and
diffs are retained. Overlay the tested current-source scripts as well; do not
silently reuse the weaker image copies. Application/config baseline files match.

Evidence is stored in the operations workspace under
`artifacts/rotation-rebase-20260919/`. No production deployment, enabled plan,
trust root installation, shared-PostgreSQL mutation or live canary is performed.
The next release gates are qualification against a verified current shared-data
copy with recreation/rollback evidence, a candidate-specific first-start gate,
external signer/trust-root provisioning and matched candidate OFF deployment.
Q3 and Q4 remain open.
