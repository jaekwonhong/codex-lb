"""Small, transport-independent contracts for foreground owner recovery."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.db.models import AccountStatus

OWNER_WAIT_BUDGET_SECONDS = 2.0
OWNER_CONTROL_BUDGET_SECONDS = 5.0

RecoveryReason = Literal["cooldown", "quota_exhausted", "headroom", "unavailable"]


@dataclass(frozen=True, slots=True)
class OwnerRecoveryHint:
    reason: RecoveryReason
    retry_at: float | None = None

    def retry_after(self, now: float) -> float | None:
        if self.retry_at is None or not math.isfinite(self.retry_at):
            return None
        return max(0.0, self.retry_at - now)


@dataclass(slots=True)
class OwnerRecoveryBudget:
    """One logical turn's recovery budget; never the model-generation deadline.

    Start only when recovery is needed, not at request creation or before model
    generation. Rebuilt request states share this same object. Reserving a wait
    before yielding also prevents nested callers from spending it twice.
    """

    started_at: float | None = None
    waited_seconds: float = 0.0
    spent_seconds: float = 0.0

    @property
    def engaged(self) -> bool:
        return self.started_at is not None or self.spent_seconds > 0 or self.waited_seconds > 0

    def remaining(self, now: float) -> float:
        active_seconds = 0.0 if self.started_at is None else max(0.0, now - self.started_at)
        return max(0.0, OWNER_CONTROL_BUDGET_SECONDS - self.spent_seconds - active_seconds)

    def start(self, now: float) -> None:
        if self.started_at is None:
            self.started_at = now

    def pause(self, now: float) -> None:
        """Exclude upstream execution while retaining this turn's spent budget."""
        if self.started_at is not None:
            self.spent_seconds += max(0.0, now - self.started_at)
            self.started_at = None

    def reserve_wait(self, delay: float, *, now: float, request_remaining: float) -> float | None:
        self.start(now)
        if not math.isfinite(delay) or delay < 0:
            return None
        # Never clip a real upstream hold to fit UX and then retry too early.
        allowance = min(
            OWNER_WAIT_BUDGET_SECONDS - self.waited_seconds,
            self.remaining(now),
            request_remaining,
        )
        if allowance <= 0 or delay > allowance:
            return None
        if delay == 0:
            # Permit one immediate re-selection, but not an unbounded busy loop
            # when a stale snapshot keeps advertising the elapsed horizon.
            self.waited_seconds = OWNER_WAIT_BUDGET_SECONDS
            return 0.0
        self.waited_seconds += delay
        return delay


def confirmed_quota_deadline(
    *,
    status: AccountStatus,
    blocked_at: float | None,
    windows: tuple[tuple[float | None, int | None, datetime | None], ...],
    now: float,
    freshness_seconds: float,
) -> float | None:
    """A real block + later fresh exhaustion is stronger than a default hold.

    Callers supply only windows applicable to this request's quota/credit policy.
    This never creates a rejection from an advisory percentage on an ACTIVE row.
    Nor can in-flight pressure, stale/future samples or an expired window prove
    continued exhaustion. No DB write occurs here.
    """
    if status not in (AccountStatus.RATE_LIMITED, AccountStatus.QUOTA_EXCEEDED) or blocked_at is None:
        return None
    deadlines: list[float] = []
    for used, reset_at, recorded_at in windows:
        if used is None or not math.isfinite(used) or used < 100 or reset_at is None or reset_at <= now:
            continue
        if recorded_at is None:
            continue
        observed = recorded_at.replace(tzinfo=timezone.utc) if recorded_at.tzinfo is None else recorded_at
        observed_at = observed.timestamp()
        if int(observed_at) <= int(blocked_at) or not now - freshness_seconds <= observed_at <= now:
            continue
        deadlines.append(float(reset_at))
    # Both applicable windows must have recovered before the account is usable.
    return max(deadlines) if deadlines else None
