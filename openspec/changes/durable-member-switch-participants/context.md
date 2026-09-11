# Receipt boundary

The parent is `member-switch-independent-review-20260906`, unchanged. The overall
run remains authoritative in the backend database; Companion receipts describe
only its three participant actions. One private JSON document, atomically replaced
after a flushed write, records command identity, pending/completed state and typed
results. It stores a fingerprint, not device codes, credentials or CDP handles.
The existing single-Launcher-per-profile boundary is still mandatory.

Request fingerprints use SHA256 over UTF-8 length-prefixed fields: command ID,
client flow ID, action, membership operation ID, the six identity fields in schema
order, browser operation ID, verification URL and user code. A null optional field
is represented by an empty string. Length is the UTF-8 byte length, followed by
`:` and the field bytes. This avoids JSON encoder or delimiter ambiguities across
C# and Python. Action validation rejects irrelevant optional parameters.

Manual flow: membership confirmed -> session prepared -> auth prepared -> browser
opened -> auth confirmed -> browser closed -> finalized. A reconciled session
receipt proves a completed preparation attempt, not perpetual login validity.
OAuth/browser services retain their own identity checks. A fresh session attempt
can be requested explicitly before auth if the earlier session is no longer useful.

Example: Companion closes a browser and commits its receipt, then the response is
lost. Explicit reconciliation reads that exact receipt and updates the parent;
the close is not repeated. If Companion instead stops after the driver ran but
before completion was stored, the pending record remains blocked for manual review.

Target handles remain runtime-bound: a completed open receipt survives restart,
but it does not prove that a particular CDP port/target still belongs to the same
browser. This iteration intentionally refuses cross-incarnation close rather than
restoring an unverified handle. Completing a lost close/session response across
restart is supported; universal browser/OAuth crash recovery is not claimed.
No automation, rollout, operational migration or old-run import is performed.
