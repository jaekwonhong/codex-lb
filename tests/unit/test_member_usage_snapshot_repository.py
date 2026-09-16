from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    MemberRotationQuotaOperation,
    ResetCreditRedeemRequest,
    WorkspaceMemberFinalUsageSnapshot,
)
from app.modules.member_auth_handoff.usage_snapshot_repository import (
    FinalUsageSnapshotInput,
    MemberUsageSnapshotRepository,
)

pytestmark = pytest.mark.unit

WORKSPACE_ID = "cdp-1"
WORKSPACE_ACCOUNT_ID = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _observations(
    observed_at: datetime,
    *,
    five_hour_used: float = 91.0,
    weekly_used: float = 73.0,
    five_hour_reset: int = 1_800_000_000,
    weekly_reset: int = 1_800_500_000,
) -> tuple[FinalUsageSnapshotInput, FinalUsageSnapshotInput]:
    return (
        FinalUsageSnapshotInput(
            logical_window="5h",
            source_window="primary",
            source_workspace_id=WORKSPACE_ID,
            source_workspace_account_id=WORKSPACE_ACCOUNT_ID,
            source_account_id="local-account-1",
            source_user_id="user-MemberA",
            source_email="member-a@example.com",
            used_percent=five_hour_used,
            reset_at=five_hour_reset,
            window_minutes=300,
            observed_at=observed_at,
            fetch_provenance="live_upstream_fetch",
            fetch_succeeded=True,
            usage_written=False,
        ),
        FinalUsageSnapshotInput(
            logical_window="weekly",
            source_window="secondary",
            source_workspace_id=WORKSPACE_ID,
            source_workspace_account_id=WORKSPACE_ACCOUNT_ID,
            source_account_id="local-account-1",
            source_user_id="user-MemberA",
            source_email="member-a@example.com",
            used_percent=weekly_used,
            reset_at=weekly_reset,
            window_minutes=10_080,
            observed_at=observed_at,
            fetch_provenance="live_upstream_fetch",
            fetch_succeeded=True,
            usage_written=True,
        ),
    )


async def _retain(
    repository: MemberUsageSnapshotRepository,
    *,
    epoch: str,
    observed_at: datetime,
    five_hour_used: float = 91.0,
    weekly_used: float = 73.0,
):
    return await repository.retain_final_snapshots(
        workspace_id=WORKSPACE_ID,
        workspace_account_id=WORKSPACE_ACCOUNT_ID,
        account_id="local-account-1",
        preset_id="member-a",
        email="Member-A@example.com",
        user_id="user-MemberA",
        membership_epoch=epoch,
        observations=_observations(
            observed_at,
            five_hour_used=five_hour_used,
            weekly_used=weekly_used,
        ),
    )


@pytest.mark.asyncio
async def test_final_5h_and_weekly_snapshots_are_retained_atomically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = MemberUsageSnapshotRepository(session, clock=clock)
        five_hour, weekly = await _retain(
            repository,
            epoch="membership-epoch-1",
            observed_at=now,
        )

        assert five_hour.logical_window == "5h" and five_hour.source_window == "primary"
        assert five_hour.used_percent == 91.0 and five_hour.window_minutes == 300
        assert weekly.logical_window == "weekly" and weekly.source_window == "secondary"
        assert weekly.used_percent == 73.0 and weekly.window_minutes == 10_080
        assert five_hour.fetch_succeeded and not five_hour.usage_written
        assert weekly.fetch_succeeded and weekly.usage_written


@pytest.mark.asyncio
async def test_later_account_reuse_does_not_overwrite_prior_membership_epoch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = MemberUsageSnapshotRepository(session, clock=clock)
        first = await _retain(
            repository,
            epoch="membership-epoch-1",
            observed_at=now,
        )
        clock.current = now + timedelta(days=10)
        await _retain(
            repository,
            epoch="membership-epoch-2",
            observed_at=now + timedelta(days=10),
            five_hour_used=15.0,
            weekly_used=20.0,
        )

        history = await repository.list_history(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            user_id="user-MemberA",
        )
        first_epoch = [row for row in history if row.membership_epoch == "membership-epoch-1"]
        assert len(history) == 4 and len(first_epoch) == 2
        assert {row.used_percent for row in first_epoch} == {first[0].used_percent, first[1].used_percent}
        assert {row.reset_at for row in first_epoch} == {first[0].reset_at, first[1].reset_at}


@pytest.mark.asyncio
async def test_identical_final_snapshot_retry_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=MutableClock(now))
        first = await _retain(
            repository,
            epoch="membership-epoch-idempotent",
            observed_at=now,
        )
        second = await _retain(
            repository,
            epoch="membership-epoch-idempotent",
            observed_at=now,
        )

        assert [item.id for item in second] == [item.id for item in first]
        count = int(await session.scalar(select(func.count()).select_from(WorkspaceMemberFinalUsageSnapshot)) or 0)
        assert count == 2


@pytest.mark.asyncio
async def test_reset_invalidation_respects_cutoff_and_preserves_original_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cutoff = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(cutoff - timedelta(minutes=1))
        repository = MemberUsageSnapshotRepository(session, clock=clock)
        original = await _retain(
            repository,
            epoch="membership-epoch-before",
            observed_at=cutoff - timedelta(minutes=2),
        )
        session.add(
            MemberRotationQuotaOperation(
                operation_id="rotation-history-1",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                requested_at=cutoff - timedelta(hours=1),
                initial_admission_code="admitted",
                reserved_at=cutoff - timedelta(hours=1),
                remove_requested_at=cutoff - timedelta(minutes=30),
                remove_effect="unknown",
            )
        )
        await session.commit()
        rotation_before = await session.get(MemberRotationQuotaOperation, "rotation-history-1")
        assert rotation_before is not None
        rotation_before_values = (
            rotation_before.requested_at,
            rotation_before.reserved_at,
            rotation_before.remove_requested_at,
            rotation_before.remove_effect,
            rotation_before.invite_effect,
        )
        credits_before = int(await session.scalar(select(func.count()).select_from(ResetCreditRedeemRequest)) or 0)

        invalidation = await repository.invalidate_historical_reset_schedules(cutoff_at=cutoff)

        clock.current = cutoff + timedelta(seconds=1)
        late = await _retain(
            repository,
            epoch="membership-epoch-after",
            observed_at=cutoff - timedelta(minutes=3),
            five_hour_used=40.0,
            weekly_used=50.0,
        )
        history = await repository.list_history(workspace_account_id=WORKSPACE_ACCOUNT_ID)
        old_history = [row for row in history if row.membership_epoch == "membership-epoch-before"]
        late_history = [row for row in history if row.membership_epoch == "membership-epoch-after"]

        assert invalidation.cutoff_at == cutoff.replace(tzinfo=None)
        assert invalidation.affected_count == 2
        assert len(old_history) == 2 and all(row.effective_reset_at is None for row in old_history)
        assert {row.used_percent for row in old_history} == {original[0].used_percent, original[1].used_percent}
        assert {row.reset_at for row in old_history} == {original[0].reset_at, original[1].reset_at}
        assert len(late_history) == 2 and all(row.reset_invalidation_id is None for row in late_history)
        assert {row.effective_reset_at for row in late_history} == {late[0].reset_at, late[1].reset_at}

        rotation_after = await session.get(MemberRotationQuotaOperation, "rotation-history-1", populate_existing=True)
        assert rotation_after is not None
        assert (
            rotation_after.requested_at,
            rotation_after.reserved_at,
            rotation_after.remove_requested_at,
            rotation_after.remove_effect,
            rotation_after.invite_effect,
        ) == rotation_before_values
        credits_after = int(await session.scalar(select(func.count()).select_from(ResetCreditRedeemRequest)) or 0)
        assert credits_after == credits_before == 0

        persisted = list((await session.scalars(select(WorkspaceMemberFinalUsageSnapshot))).all())
        assert len(persisted) == 4


@pytest.mark.asyncio
async def test_missing_final_window_is_rejected_without_partial_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=MutableClock(now))
        with pytest.raises(ValueError, match="one 5h and one weekly"):
            await repository.retain_final_snapshots(
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                account_id="local-account-1",
                preset_id="member-a",
                email="member-a@example.com",
                user_id="user-MemberA",
                membership_epoch="membership-epoch-incomplete",
                observations=(_observations(now)[0],),
            )

        count = int(await session.scalar(select(func.count()).select_from(WorkspaceMemberFinalUsageSnapshot)) or 0)
        assert count == 0
