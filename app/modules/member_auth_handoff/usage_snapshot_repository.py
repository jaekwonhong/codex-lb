from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, JsonValue
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils.time import to_utc_naive, utcnow
from app.db.models import WorkspaceMemberFinalUsageSnapshot, WorkspaceMemberUsageResetInvalidation
from app.db.session import sqlite_writer_section

RetainedUsageWindow = Literal["5h", "weekly"]
_REQUIRED_WINDOWS = frozenset({"5h", "weekly"})
_RESET_INVALIDATION_LOCK_KEY = "member_usage_history:reset_invalidation"


class HistoricalUsageConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FinalUsageSnapshotInput:
    logical_window: RetainedUsageWindow
    source_window: str
    source_workspace_id: str
    source_workspace_account_id: str
    source_account_id: str
    source_user_id: str
    source_email: str
    used_percent: float
    reset_at: int | None
    window_minutes: int
    observed_at: datetime
    fetch_provenance: str
    fetch_succeeded: bool
    usage_written: bool


@dataclass(frozen=True, slots=True)
class HistoricalUsageSnapshotView:
    id: str
    workspace_id: str
    workspace_account_id: str
    account_id: str
    preset_id: str
    email: str
    user_id: str
    membership_epoch: str
    logical_window: str
    source_window: str
    used_percent: float
    reset_at: int | None
    effective_reset_at: int | None
    window_minutes: int
    observed_at: datetime
    fetch_provenance: str
    fetch_succeeded: bool
    usage_written: bool
    retained_at: datetime
    reset_invalidation_id: str | None


class _VersionedFetchProvenance(BaseModel):
    schema_version: Literal[2]
    five_hour_availability: Literal["observed", "not_provided"]
    evaluation_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    source_account_id: str = Field(min_length=1)
    source_workspace_account_id: str = Field(min_length=1)
    source_user_id: str = Field(min_length=1)
    source_email: str = Field(min_length=1)
    fetch_id: str = Field(min_length=1)
    requested_workspace_account_id: str = Field(min_length=1)
    account_workspace_id: str | None
    payload_workspace_id: str | None
    credential_source: Literal["stored"]
    started_at: AwareDatetime
    observed_at: AwareDatetime


def _provenance_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    values: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in {"schema_version", "five_hour_availability"} and key in values:
            raise ValueError("final usage provenance has duplicate version metadata")
        values[key] = value
    return values


def _normalized_inputs(observations: Sequence[FinalUsageSnapshotInput]) -> dict[str, FinalUsageSnapshotInput]:
    by_window: dict[str, FinalUsageSnapshotInput] = {item.logical_window: item for item in observations}
    if not observations or len(by_window) != len(observations):
        raise ValueError("final usage retention requires one 5h and one weekly observation or proven 5h absence")
    provenance_text = observations[0].fetch_provenance.strip()
    try:
        raw = json.loads(provenance_text, object_pairs_hook=_provenance_object)
    except json.JSONDecodeError as exc:
        if provenance_text.startswith(("{", "[")):
            raise ValueError("final usage provenance JSON is malformed") from exc
        raw = None  # Legacy opaque provenance only supports a complete pair.
    provenance = None
    if isinstance(raw, dict):
        if "schema_version" in raw:
            version = raw["schema_version"]
            # bool and float equality must not select a supported integer version.
            if type(version) is not int or version not in {1, 2}:
                raise ValueError("final usage provenance version is invalid or unsupported")
            if version == 2:
                provenance = _VersionedFetchProvenance.model_validate_json(provenance_text)
            elif "five_hour_availability" in raw:
                raise ValueError("legacy final usage provenance contains versioned availability")
        elif "five_hour_availability" in raw or {"evaluation_id", "requested_workspace_account_id"} <= raw.keys():
            # Recognizable versioned evidence cannot become opaque by losing its tag.
            raise ValueError("final usage provenance version is missing")
    required = {"weekly"} if provenance and provenance.five_hour_availability == "not_provided" else _REQUIRED_WINDOWS
    if set(by_window) != required:
        raise ValueError("final usage retention requires one 5h and one weekly observation or proven 5h absence")
    for item in observations:
        if not item.source_window.strip() or not item.fetch_provenance.strip():
            raise ValueError("final usage observation metadata is incomplete")
        if item.window_minutes <= 0 or not item.fetch_succeeded:
            raise ValueError("final usage observation is not eligible for retention")
        if item.fetch_provenance.strip() != provenance_text or to_utc_naive(item.observed_at) != to_utc_naive(
            observations[0].observed_at
        ):
            raise ValueError("final usage observation provenance mismatch")
        if provenance is not None:
            if (
                provenance.workspace_id != item.source_workspace_id
                or provenance.source_account_id != item.source_account_id
                or provenance.source_workspace_account_id != item.source_workspace_account_id
                or provenance.requested_workspace_account_id != item.source_workspace_account_id
                or provenance.source_user_id != item.source_user_id
                or provenance.source_email != item.source_email.strip().casefold()
                or to_utc_naive(provenance.observed_at) != to_utc_naive(item.observed_at)
                or to_utc_naive(provenance.started_at) > to_utc_naive(provenance.observed_at)
                or (
                    provenance.account_workspace_id is not None
                    and provenance.payload_workspace_id is not None
                    and provenance.account_workspace_id != provenance.payload_workspace_id
                )
            ):
                raise ValueError("final usage observation provenance identity mismatch")
            if (
                item.window_minutes != (300 if item.logical_window == "5h" else 10080)
                or not math.isfinite(item.used_percent)
                or item.used_percent < 0
                or item.reset_at is None
                or item.reset_at <= provenance.observed_at.timestamp()
            ):
                raise ValueError("final usage observation window is invalid")
    return by_window


def _view_input(row: HistoricalUsageSnapshotView) -> FinalUsageSnapshotInput:
    if row.logical_window not in {"5h", "weekly"}:
        raise ValueError("invalid retained window")
    return FinalUsageSnapshotInput(
        logical_window="5h" if row.logical_window == "5h" else "weekly",
        source_window=row.source_window,
        source_workspace_id=row.workspace_id,
        source_workspace_account_id=row.workspace_account_id,
        source_account_id=row.account_id,
        source_user_id=row.user_id,
        source_email=row.email,
        used_percent=row.used_percent,
        reset_at=row.reset_at,
        window_minutes=row.window_minutes,
        observed_at=row.observed_at,
        fetch_provenance=row.fetch_provenance,
        fetch_succeeded=row.fetch_succeeded,
        usage_written=row.usage_written,
    )


def retained_five_hour_state(
    rows: Sequence[HistoricalUsageSnapshotView],
) -> Literal["observed", "not_provided", "unknown"]:
    """Share recovery validation with display; a missing row alone proves nothing."""
    try:
        normalized = _normalized_inputs([_view_input(row) for row in rows])
    except ValueError:
        return "unknown"
    return "observed" if "5h" in normalized else "not_provided"


def _view(row: WorkspaceMemberFinalUsageSnapshot) -> HistoricalUsageSnapshotView:
    return HistoricalUsageSnapshotView(
        id=row.id,
        workspace_id=row.workspace_id,
        workspace_account_id=row.workspace_account_id,
        account_id=row.account_id,
        preset_id=row.preset_id,
        email=row.email,
        user_id=row.user_id,
        membership_epoch=row.membership_epoch,
        logical_window=row.logical_window,
        source_window=row.source_window,
        used_percent=row.used_percent,
        reset_at=row.reset_at,
        effective_reset_at=None if row.reset_invalidation_id is not None else row.reset_at,
        window_minutes=row.window_minutes,
        observed_at=row.observed_at,
        fetch_provenance=row.fetch_provenance,
        fetch_succeeded=row.fetch_succeeded,
        usage_written=row.usage_written,
        retained_at=row.retained_at,
        reset_invalidation_id=row.reset_invalidation_id,
    )


class MemberUsageSnapshotRepository:
    """Retain final member usage evidence beyond account and membership lifetime."""

    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._clock = clock

    def _dialect_name(self) -> str:
        bind = self._session.get_bind()
        return bind.dialect.name if bind is not None else "sqlite"

    async def _now(self) -> datetime:
        if self._clock is not None:
            return to_utc_naive(self._clock())
        if self._dialect_name() == "postgresql":
            value = await self._session.scalar(text("SELECT clock_timestamp()"))
        elif self._dialect_name() == "sqlite":
            value = await self._session.scalar(text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')"))
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
        else:
            value = utcnow()
        if not isinstance(value, datetime):
            raise RuntimeError("database clock did not return a datetime")
        return to_utc_naive(value)

    async def _lock_epoch(self, workspace_account_id: str, membership_epoch: str) -> None:
        await self._session.commit()
        if self._dialect_name() == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": _RESET_INVALIDATION_LOCK_KEY},
            )
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"member_usage_history:{workspace_account_id}:{membership_epoch}"},
            )
        elif self._dialect_name() == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    def _same_evidence(
        row: WorkspaceMemberFinalUsageSnapshot,
        *,
        workspace_id: str,
        workspace_account_id: str,
        account_id: str,
        preset_id: str,
        email: str,
        user_id: str,
        membership_epoch: str,
        item: FinalUsageSnapshotInput,
    ) -> bool:
        return (
            row.workspace_id == workspace_id
            and row.workspace_account_id == workspace_account_id
            and row.account_id == account_id
            and row.preset_id == preset_id
            and row.email == email
            and row.user_id == user_id
            and row.membership_epoch == membership_epoch
            and row.logical_window == item.logical_window
            and row.source_window == item.source_window.strip().casefold()
            and row.used_percent == item.used_percent
            and row.reset_at == item.reset_at
            and row.window_minutes == item.window_minutes
            and to_utc_naive(row.observed_at) == to_utc_naive(item.observed_at)
            and row.fetch_provenance == item.fetch_provenance.strip()
            and row.fetch_succeeded == item.fetch_succeeded
            and row.usage_written == item.usage_written
        )

    async def retain_final_snapshots(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
        account_id: str,
        preset_id: str,
        email: str,
        user_id: str,
        membership_epoch: str,
        observations: list[FinalUsageSnapshotInput] | tuple[FinalUsageSnapshotInput, ...],
    ) -> tuple[HistoricalUsageSnapshotView, ...]:
        normalized = _normalized_inputs(observations)
        normalized_email = email.strip().casefold()
        identity = (
            workspace_id,
            workspace_account_id,
            account_id,
            preset_id,
            normalized_email,
            user_id,
            membership_epoch,
        )
        if not all(value.strip() for value in identity):
            raise ValueError("final usage snapshot identity is incomplete")
        for item in normalized.values():
            if (
                item.source_workspace_id != workspace_id
                or item.source_workspace_account_id != workspace_account_id
                or item.source_account_id != account_id
                or item.source_user_id != user_id
                or item.source_email.strip().casefold() != normalized_email
            ):
                raise ValueError("final usage snapshot source identity mismatch")
        async with sqlite_writer_section():
            await self._lock_epoch(workspace_account_id, membership_epoch)
            captured_at = await self._now()
            existing = list(
                (
                    await self._session.scalars(
                        select(WorkspaceMemberFinalUsageSnapshot)
                        .where(
                            WorkspaceMemberFinalUsageSnapshot.workspace_account_id == workspace_account_id,
                            WorkspaceMemberFinalUsageSnapshot.user_id == user_id,
                            WorkspaceMemberFinalUsageSnapshot.membership_epoch == membership_epoch,
                        )
                        .order_by(WorkspaceMemberFinalUsageSnapshot.logical_window)
                    )
                ).all()
            )
            if existing:
                if len(existing) != len(normalized) or {row.logical_window for row in existing} != set(normalized):
                    await self._session.rollback()
                    raise HistoricalUsageConflict("historical usage epoch is incomplete")
                for row in existing:
                    if not self._same_evidence(
                        row,
                        workspace_id=workspace_id,
                        workspace_account_id=workspace_account_id,
                        account_id=account_id,
                        preset_id=preset_id,
                        email=normalized_email,
                        user_id=user_id,
                        membership_epoch=membership_epoch,
                        item=normalized[row.logical_window],
                    ):
                        await self._session.rollback()
                        raise HistoricalUsageConflict("historical usage epoch contains different evidence")
                ordered = sorted(existing, key=lambda row: 0 if row.logical_window == "5h" else 1)
                views = tuple(_view(row) for row in ordered)
                await self._session.rollback()
                return views

            rows: list[WorkspaceMemberFinalUsageSnapshot] = []
            for logical_window in sorted(normalized):
                item = normalized[logical_window]
                rows.append(
                    WorkspaceMemberFinalUsageSnapshot(
                        workspace_id=workspace_id,
                        workspace_account_id=workspace_account_id,
                        account_id=account_id,
                        preset_id=preset_id,
                        email=normalized_email,
                        user_id=user_id,
                        membership_epoch=membership_epoch,
                        logical_window=logical_window,
                        source_window=item.source_window.strip().casefold(),
                        used_percent=item.used_percent,
                        reset_at=item.reset_at,
                        window_minutes=item.window_minutes,
                        observed_at=to_utc_naive(item.observed_at),
                        fetch_provenance=item.fetch_provenance.strip(),
                        fetch_succeeded=item.fetch_succeeded,
                        usage_written=item.usage_written,
                        retained_at=captured_at,
                    )
                )
            self._session.add_all(rows)
            await self._session.commit()
            for row in rows:
                await self._session.refresh(row)
            return tuple(_view(row) for row in rows)

    async def recover_final_snapshot_epoch(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
        account_id: str,
        preset_id: str,
        email: str,
        user_id: str,
        membership_epoch: str,
    ) -> tuple[HistoricalUsageSnapshotView, ...] | None:
        """Recover an already committed immutable epoch after parent-state loss.

        The historical table's unique key is narrower than the full source
        identity, so recovery first loads by that durable epoch key and then
        validates every identity/provenance invariant before returning ids.
        """
        normalized_email = email.strip().casefold()
        rows = list(
            (
                await self._session.scalars(
                    select(WorkspaceMemberFinalUsageSnapshot)
                    .where(
                        WorkspaceMemberFinalUsageSnapshot.workspace_account_id == workspace_account_id,
                        WorkspaceMemberFinalUsageSnapshot.user_id == user_id,
                        WorkspaceMemberFinalUsageSnapshot.membership_epoch == membership_epoch,
                    )
                    .order_by(WorkspaceMemberFinalUsageSnapshot.logical_window)
                )
            ).all()
        )
        if not rows:
            return None
        try:
            _normalized_inputs([_view_input(_view(row)) for row in rows])
        except ValueError as exc:
            raise HistoricalUsageConflict("historical usage epoch is incomplete or invalid") from exc
        if any(
            row.workspace_id != workspace_id
            or row.account_id != account_id
            or row.preset_id != preset_id
            or row.email != normalized_email
            or not row.fetch_succeeded
            for row in rows
        ):
            raise HistoricalUsageConflict("historical usage epoch identity mismatch")
        if (
            len({row.fetch_provenance for row in rows}) != 1
            or len({to_utc_naive(row.observed_at) for row in rows}) != 1
        ):
            raise HistoricalUsageConflict("historical usage epoch provenance mismatch")
        ordered = sorted(rows, key=lambda row: 0 if row.logical_window == "5h" else 1)
        return tuple(_view(row) for row in ordered)

    async def invalidate_historical_reset_schedules(
        self,
        *,
        cutoff_at: datetime,
    ) -> WorkspaceMemberUsageResetInvalidation:
        cutoff = to_utc_naive(cutoff_at)
        invalidation = WorkspaceMemberUsageResetInvalidation(cutoff_at=cutoff)
        async with sqlite_writer_section():
            await self._session.commit()
            if self._dialect_name() == "sqlite":
                await self._session.execute(text("BEGIN IMMEDIATE"))
            elif self._dialect_name() == "postgresql":
                await self._session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": _RESET_INVALIDATION_LOCK_KEY},
                )
            self._session.add(invalidation)
            await self._session.flush()
            result = await self._session.execute(
                update(WorkspaceMemberFinalUsageSnapshot)
                .where(
                    WorkspaceMemberFinalUsageSnapshot.reset_invalidation_id.is_(None),
                    WorkspaceMemberFinalUsageSnapshot.reset_at.is_not(None),
                    WorkspaceMemberFinalUsageSnapshot.observed_at <= cutoff,
                    WorkspaceMemberFinalUsageSnapshot.retained_at <= cutoff,
                )
                .values(reset_invalidation_id=invalidation.id)
                .execution_options(synchronize_session=False)
            )
            invalidation.affected_count = max(getattr(result, "rowcount", 0) or 0, 0)
            await self._session.commit()
            await self._session.refresh(invalidation)
            return invalidation

    async def list_history(
        self,
        *,
        workspace_account_id: str | None = None,
        user_id: str | None = None,
    ) -> list[HistoricalUsageSnapshotView]:
        stmt = select(WorkspaceMemberFinalUsageSnapshot)
        if workspace_account_id is not None:
            stmt = stmt.where(WorkspaceMemberFinalUsageSnapshot.workspace_account_id == workspace_account_id)
        if user_id is not None:
            stmt = stmt.where(WorkspaceMemberFinalUsageSnapshot.user_id == user_id)
        stmt = stmt.order_by(
            WorkspaceMemberFinalUsageSnapshot.retained_at,
            WorkspaceMemberFinalUsageSnapshot.membership_epoch,
            WorkspaceMemberFinalUsageSnapshot.logical_window,
        )
        return [_view(row) for row in (await self._session.scalars(stmt)).all()]
