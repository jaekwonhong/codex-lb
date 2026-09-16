# P1 — Weekly observation integration

Implemented against foundation `08458354efe5ea27f24de76b7fa06bba1f6bd1ed`.
The S1 interpretation contract is unchanged. There is no schema migration,
controller, UI, reset-credit executor, or membership executor in this change.

## Entry point

Use `UsageUpdater.force_weekly_observation(account)`. It reuses forced-refresh
singleflight, routing, credential retry, normalization, and usage persistence,
but skips the legacy rotation-event observer and its extra confirmation fetch.

```python
from datetime import datetime, timezone

from app.core.usage.weekly_observation import UsageAccountIdentity

# Resolve from authoritative current membership plus a unique account match.
# These values must not be copied from the observation being assessed.
current_member = UsageAccountIdentity(
    account_id=auth_account_id,
    workspace_account_id=workspace_account_id,
    user_id=user_id,
    email=email,
)
observation = await updater.force_weekly_observation(account)
assessment = observation.assess(
    current_member,
    now=datetime.now(timezone.utc),
    not_before=required_fetch_boundary,  # datetime, or None for ordinary observation
)
```

Only `assessment.state == "exhausted"` is Weekly exhaustion evidence. It is not
membership authorization. Re-resolve current membership and assess again at each
effect boundary. The catalog contains candidates, not proof of current membership;
ambiguous/missing account matches must stop before consuming an observation.
Catalog `workspace_id` is a logical alias, distinct from both upstream
`workspace_account_id` and the account's usage-response workspace metadata.

## Evidence and freshness

- `observation.window`: original `source_slot`, `raw_used_percent`, normalized
  `window_minutes`, original `limit_window_seconds`, and resolved epoch `reset_at`.
- `observation.provenance`: fetch UUID, immutable local account/workspace/user/email
  identity, requested workspace header, account/payload workspace metadata,
  credential source, and UTC `started_at`/`observed_at`.
- `fetch_succeeded` and `usage_written` are independent. A successful unchanged
  fetch can remain evidence with `usage_written=False`; stored rows are never a
  fallback after a failed or non-Weekly fetch.

Classification reuses existing payload normalization, duration-to-minutes
conversion, and the same-fetch Weekly tiebreak. Weekly-only primary stays primary
in storage and provenance. Monthly, 5H, and metadata-free placeholders do not
become Weekly. Historical partial-minute rounding is preserved, including
604799 seconds normalizing to 10080 minutes.

`assess()` returns `unknown`, `available`, or `exhausted`, with a typed reason for
unknown. It checks the complete member identity, fetch provenance, the existing
usage freshness horizon (currently 180 seconds), raw finite numeric usage, and
an unelapsed reset. Exhaustion uses raw `used_percent >= 100`, without display
rounding. Missing reset metadata is unknown. Original values remain immutable
when an observation ages or its reset elapses.

For P2 post-redemption reconciliation, pass a `not_before` boundary after the
operation being reconciled: the fetch must **start** at or after that boundary.
A later reply to an earlier request cannot satisfy it. Reuse the same API for
bounded re-observation; no new retry/redemption executor is introduced here.
P3 can retain the immutable raw evidence with its membership-period identity;
a saved assessment must not serve as future authorization.

Existing `force_refresh()` and `force_refresh_result()` remain compatible.
Their added receipt is discarded when the legacy confirmation path makes an
additional fetch whose payload it does not return. A cache-only freshness skip
now reports `fetch_succeeded=False`. Override-token receipts cannot establish
the stored member's principal and assess as unknown.

## Validation

Focused tests: `tests/unit/test_weekly_usage_observation.py` and
`tests/unit/test_weekly_usage_refresh.py` — 65 passed. They cover the requested
slot/window, null/placeholder, rounding, elapsed-reset, no-write/failure, 5H-only,
and exact-identity cases, plus time boundaries, immutable captures, 401 retry,
and isolation from the legacy event/confirmation path.

Full relevant usage/account-mapper/probe unit selection: 383 passed (including
the focused tests). Usage integration selection: 86 passed, 39 skipped:
15 require PostgreSQL and 24 require the native usage-egress test binary.
Changed application files pass `ty check`; changed Python files pass Ruff lint
and format checks. The active OpenSpec change and all 65 base specifications
pass strict validation with OpenSpec 1.11.0.
No live reset credit or membership operation was performed.
