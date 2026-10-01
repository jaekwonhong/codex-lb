"""Timestamp/credit evidence shared by selection and read-only owner advice."""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import AdditionalUsageHistory, UsageHistory

type UsageWindowEntry = UsageHistory | AdditionalUsageHistory


def usage_entry_recorded_after_block(entry: UsageWindowEntry | None, blocked_at: float) -> bool:
    if entry is None or entry.recorded_at is None:
        return False
    recorded_at = entry.recorded_at
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    # Persistence truncates block timestamps to whole seconds. A sample
    # within that same second cannot prove it was captured after the block.
    return int(recorded_at.timestamp()) > int(blocked_at)


def extract_credit_status(
    *entries: UsageWindowEntry | None,
    recorded_after: float | None = None,
) -> tuple[bool | None, bool | None, float | None]:
    credit_entries: list[UsageHistory] = [
        entry
        for entry in entries
        if isinstance(entry, UsageHistory)
        and (recorded_after is None or usage_entry_recorded_after_block(entry, recorded_after))
        and not (entry.credits_has is None and entry.credits_unlimited is None and entry.credits_balance is None)
    ]
    if not credit_entries:
        return None, None, None
    entry = max(
        credit_entries,
        key=lambda item: item.recorded_at if item.recorded_at is not None else datetime.min,
    )
    if entry is not None:
        return entry.credits_has, entry.credits_unlimited, entry.credits_balance
    return None, None, None
