"""Weekly evidence from one actual fetch, evaluated against the current member.

Stored/display usage rows deliberately cannot construct this evidence. Consumers
must assess again at each decision boundary, using an independently resolved
current member and the current time; an earlier assessment is not authorization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.core.usage import (
    is_primary_window_minutes,
    is_weekly_window_minutes,
    normalize_rate_limit_windows,
    should_use_weekly_primary,
)
from app.core.usage.models import UsagePayload
from app.core.usage.refresh_policy import usage_freshness_horizon_seconds
from app.core.usage.types import UsageWindowRow
from app.core.usage.window_metadata import reset_at_epoch, window_minutes


@dataclass(frozen=True, slots=True)
class UsageAccountIdentity:
    account_id: str
    workspace_account_id: str | None
    user_id: str | None
    email: str

    def matches(self, current_member: UsageAccountIdentity) -> bool:
        """Require the local credential slot AND the complete upstream seat identity."""
        return (
            bool(
                self.account_id.strip()
                and self.workspace_account_id
                and self.workspace_account_id.strip()
                and self.user_id
                and self.user_id.strip()
                and self.email.strip()
            )
            and self.account_id == current_member.account_id
            and self.workspace_account_id == current_member.workspace_account_id
            and self.user_id == current_member.user_id
            and self.email.casefold() == current_member.email.casefold()
        )


@dataclass(frozen=True, slots=True)
class UsageFetchProvenance:
    fetch_id: str
    identity: UsageAccountIdentity
    requested_workspace_account_id: str | None
    account_workspace_id: str | None
    payload_workspace_id: str | None
    credential_source: Literal["stored", "override"]
    started_at: datetime
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ClassifiedUsageWindowObservation:
    source_slot: Literal["primary", "secondary"]
    raw_used_percent: float | None
    window_minutes: int | None
    limit_window_seconds: int | None
    reset_at: int | None


# P1 originally exposed only Weekly evidence. Keep that public name while G1
# adds the same-fetch 5H window needed by immutable pre-removal retention.
WeeklyWindowObservation = ClassifiedUsageWindowObservation
FiveHourWindowObservation = ClassifiedUsageWindowObservation


WeeklyUnknownReason = Literal[
    "fetch_failed",
    "fetch_not_observed",
    "identity_mismatch",
    "unverified_credentials",
    "weekly_missing",
    "invalid_fetch_time",
    "fetch_before_boundary",
    "stale",
    "usage_missing",
    "usage_invalid",
    "reset_missing",
    "reset_elapsed",
]


@dataclass(frozen=True, slots=True)
class WeeklyUsageAssessment:
    state: Literal["unknown", "available", "exhausted"]
    reason: WeeklyUnknownReason | None = None


@dataclass(frozen=True, slots=True)
class WeeklyUsageObservation:
    """Immutable raw evidence. Freshness/exhaustion is computed, never stored."""

    fetch_succeeded: bool
    usage_written: bool
    provenance: UsageFetchProvenance | None = None
    window: WeeklyWindowObservation | None = None

    def assess(
        self,
        current_member: UsageAccountIdentity,
        *,
        now: datetime,
        not_before: datetime | None = None,
    ) -> WeeklyUsageAssessment:
        if not self.fetch_succeeded:
            return WeeklyUsageAssessment("unknown", "fetch_failed")
        provenance = self.provenance
        if provenance is None:
            return WeeklyUsageAssessment("unknown", "fetch_not_observed")
        if provenance.credential_source != "stored":
            # An arbitrary override token is not proof of the stored seat's principal.
            return WeeklyUsageAssessment("unknown", "unverified_credentials")
        if (
            not provenance.identity.matches(current_member)
            or provenance.requested_workspace_account_id != current_member.workspace_account_id
            or (
                provenance.account_workspace_id is not None
                and provenance.payload_workspace_id is not None
                and provenance.account_workspace_id != provenance.payload_workspace_id
            )
        ):
            return WeeklyUsageAssessment("unknown", "identity_mismatch")
        window = self.window
        if window is None:
            return WeeklyUsageAssessment("unknown", "weekly_missing")
        current_time = _utc(now)
        started_at = _utc(provenance.started_at)
        observed_at = _utc(provenance.observed_at)
        if started_at > observed_at or observed_at > current_time:
            return WeeklyUsageAssessment("unknown", "invalid_fetch_time")
        if not_before is not None and started_at < _utc(not_before):
            return WeeklyUsageAssessment("unknown", "fetch_before_boundary")
        if (current_time - observed_at).total_seconds() >= usage_freshness_horizon_seconds():
            return WeeklyUsageAssessment("unknown", "stale")
        used = window.raw_used_percent
        if used is None:
            return WeeklyUsageAssessment("unknown", "usage_missing")
        if not math.isfinite(used) or used < 0:
            return WeeklyUsageAssessment("unknown", "usage_invalid")
        if window.reset_at is None:
            return WeeklyUsageAssessment("unknown", "reset_missing")
        if window.reset_at <= current_time.timestamp():
            return WeeklyUsageAssessment("unknown", "reset_elapsed")
        return WeeklyUsageAssessment("exhausted" if used >= 100 else "available")


@dataclass(frozen=True, slots=True)
class RotationUsageObservation:
    """One actual Usage fetch with the windows needed by the rotation foundation."""

    fetch_succeeded: bool
    usage_written: bool
    provenance: UsageFetchProvenance | None = None
    five_hour_window: FiveHourWindowObservation | None = None
    weekly_window: WeeklyWindowObservation | None = None

    @property
    def weekly_observation(self) -> WeeklyUsageObservation:
        return WeeklyUsageObservation(
            fetch_succeeded=self.fetch_succeeded,
            usage_written=self.usage_written,
            provenance=self.provenance,
            window=self.weekly_window,
        )


def weekly_window_from_payload(
    payload: UsagePayload,
    *,
    observed_at: datetime,
) -> WeeklyWindowObservation | None:
    """Classify this response only; preserve the upstream slot before display remapping."""
    if payload.rate_limit is None:
        return None
    normalized = normalize_rate_limit_windows(
        payload.rate_limit.primary_window,
        payload.rate_limit.secondary_window,
    )
    candidates: dict[str, WeeklyWindowObservation] = {}
    for slot, window in (("primary", normalized.primary), ("secondary", normalized.secondary)):
        if window is None:
            continue
        minutes = window_minutes(window.limit_window_seconds)
        # Use the same duration conversion as storage; never infer duration from
        # a slot or a plan's default. Retain seconds as well as normalized minutes.
        if not is_weekly_window_minutes(minutes):
            continue
        candidates[slot] = WeeklyWindowObservation(
            source_slot="primary" if slot == "primary" else "secondary",
            raw_used_percent=window.used_percent,
            window_minutes=minutes,
            limit_window_seconds=window.limit_window_seconds,
            reset_at=reset_at_epoch(window.reset_at, window.reset_after_seconds, int(_utc(observed_at).timestamp())),
        )
    primary = candidates.get("primary")
    secondary = candidates.get("secondary")
    if primary is None:
        return secondary
    if secondary is None:
        return primary
    # Both are genuine Weekly candidates from this one fetch. Reuse the existing
    # same-fetch tiebreak; never compare with a persisted sibling's timestamp.
    primary_row = UsageWindowRow("", primary.raw_used_percent, primary.reset_at, primary.window_minutes, observed_at)
    secondary_row = UsageWindowRow(
        "", secondary.raw_used_percent, secondary.reset_at, secondary.window_minutes, observed_at
    )
    return primary if should_use_weekly_primary(primary_row, secondary_row) else secondary


def five_hour_window_from_payload(
    payload: UsagePayload,
    *,
    observed_at: datetime,
) -> FiveHourWindowObservation | None:
    """Return one unambiguous 5H window from this response only.

    Slot names are not semantic authority. A malformed response containing two
    distinct 5H-shaped slots is ambiguous and therefore cannot satisfy final
    retention; callers must fetch again instead of guessing a winner.
    """
    if payload.rate_limit is None:
        return None
    normalized = normalize_rate_limit_windows(
        payload.rate_limit.primary_window,
        payload.rate_limit.secondary_window,
    )
    candidates: list[FiveHourWindowObservation] = []
    for slot, window in (("primary", normalized.primary), ("secondary", normalized.secondary)):
        if window is None:
            continue
        minutes = window_minutes(window.limit_window_seconds)
        if not is_primary_window_minutes(minutes):
            continue
        candidates.append(
            ClassifiedUsageWindowObservation(
                source_slot="primary" if slot == "primary" else "secondary",
                raw_used_percent=window.used_percent,
                window_minutes=minutes,
                limit_window_seconds=window.limit_window_seconds,
                reset_at=reset_at_epoch(
                    window.reset_at,
                    window.reset_after_seconds,
                    int(_utc(observed_at).timestamp()),
                ),
            )
        )
    return candidates[0] if len(candidates) == 1 else None


def _utc(value: datetime) -> datetime:
    # Repository clocks use UTC-naive datetimes; never interpret them as host time.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
