from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, MemberRotationQuotaOperation
from app.modules.member_auth_handoff.rotation_events import RotationQuotaRepository

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


async def _reserve(
    repository: RotationQuotaRepository,
    clock: MutableClock,
    operation_id: str,
    at: datetime,
):
    clock.current = at
    return await repository.reserve(
        operation_id=operation_id,
        workspace_id=WORKSPACE_ID,
        workspace_account_id=WORKSPACE_ACCOUNT_ID,
    )


async def _confirm_remove(
    repository: RotationQuotaRepository,
    clock: MutableClock,
    operation_id: str,
    at: datetime,
) -> None:
    clock.current = at
    await repository.record_effect_request(operation_id, effect="remove")
    clock.current = at + timedelta(seconds=1)
    await repository.record_effect_outcome(operation_id, effect="remove", outcome="confirmed")


@pytest.mark.asyncio
async def test_rolling_24h_third_allowed_fourth_blocked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        assert (await _reserve(repository, clock, "op-1", now - timedelta(hours=2))).admitted
        assert (await _reserve(repository, clock, "op-2", now - timedelta(hours=1))).admitted

        third = await _reserve(repository, clock, "op-3", now)
        fourth = await _reserve(repository, clock, "op-4", now + timedelta(minutes=1))

        assert third.admitted and third.count_24h == 3
        assert not fourth.admitted
        assert fourth.code == "rolling_24h_limit"
        assert fourth.count_24h == 3


@pytest.mark.asyncio
async def test_rolling_168h_seventh_allowed_eighth_blocked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        for index, days_ago in enumerate((6, 5, 4, 3, 2, 1.1), start=1):
            operation_id = f"old-{index}"
            effect_base = now - timedelta(days=days_ago)
            decision = await _reserve(repository, clock, operation_id, effect_base)
            assert decision.admitted
            await _confirm_remove(repository, clock, operation_id, effect_base + timedelta(seconds=1))
            clock.current = effect_base + timedelta(seconds=3)
            await repository.mark_completed(operation_id)

        seventh = await _reserve(repository, clock, "op-7", now)
        eighth = await _reserve(repository, clock, "op-8", now + timedelta(minutes=1))

        assert seventh.admitted and seventh.count_168h == 7
        assert not eighth.admitted
        assert eighth.code == "rolling_168h_limit"
        assert eighth.count_168h == 7


@pytest.mark.asyncio
async def test_unknown_effect_keeps_quota_reserved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-1", now - timedelta(hours=2))
        await _reserve(repository, clock, "op-2", now - timedelta(hours=1))
        await _reserve(repository, clock, "op-unknown", now)

        clock.current = now + timedelta(seconds=1)
        row = await repository.record_effect_request("op-unknown", effect="remove")
        assert row.remove_effect == "unknown"
        clock.current = now + timedelta(seconds=2)
        assert not await repository.release_reservation("op-unknown")

        blocked = await _reserve(repository, clock, "op-after-unknown", now + timedelta(minutes=1))
        assert not blocked.admitted and blocked.code == "rolling_24h_limit"


@pytest.mark.asyncio
async def test_unknown_effect_cannot_be_completed_or_aged_out(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-unknown-complete", now)
        await repository.record_effect_request("op-unknown-complete", effect="remove")

        clock.current = now + timedelta(seconds=1)
        with pytest.raises(ValueError, match="unresolved effect"):
            await repository.mark_completed("op-unknown-complete")

        # Defense in depth for legacy/corrupt persisted rows that already have
        # completion stamped while an external effect is still unresolved.
        row = await session.get(MemberRotationQuotaOperation, "op-unknown-complete")
        assert row is not None
        row.completed_at = (now + timedelta(seconds=2)).replace(tzinfo=None)
        await session.commit()

        aged = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(days=8),
        )
        assert aged.count_24h == 1 and aged.count_168h == 1


@pytest.mark.asyncio
async def test_completion_without_confirmed_effect_cannot_age_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-no-effect", now)

        clock.current = now + timedelta(seconds=1)
        with pytest.raises(ValueError, match="no confirmed effect"):
            await repository.mark_completed("op-no-effect")

        held = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(days=8),
        )
        assert held.count_24h == 1 and held.count_168h == 1


@pytest.mark.asyncio
async def test_confirmed_removal_failed_invite_stays_counted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-partial", now)
        await repository.record_effect_request("op-partial", effect="remove")
        clock.current = now + timedelta(seconds=1)
        await repository.record_effect_outcome("op-partial", effect="remove", outcome="confirmed")
        clock.current = now + timedelta(seconds=2)
        await repository.record_effect_request("op-partial", effect="invite")
        clock.current = now + timedelta(seconds=3)
        await repository.record_effect_outcome(
            "op-partial",
            effect="invite",
            outcome="authoritative_non_effect",
        )

        clock.current = now + timedelta(seconds=4)
        assert not await repository.release_reservation("op-partial")
        snapshot = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(seconds=5),
        )
        assert snapshot.count_24h == 1

        aged = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(hours=169),
        )
        assert aged.count_24h == 0 and aged.count_168h == 0


@pytest.mark.asyncio
async def test_confirmed_effect_rolls_from_effect_time_not_old_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now - timedelta(days=8))
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-delayed-effect", clock.current)

        clock.current = now
        await repository.record_effect_request("op-delayed-effect", effect="remove")
        clock.current = now + timedelta(seconds=1)
        await repository.record_effect_outcome(
            "op-delayed-effect",
            effect="remove",
            outcome="confirmed",
        )

        recent = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(seconds=2),
        )
        assert recent.count_24h == 1 and recent.count_168h == 1

        aged = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(hours=169),
        )
        assert aged.count_24h == 0 and aged.count_168h == 0


@pytest.mark.asyncio
async def test_confirmed_effect_without_effect_timestamp_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now - timedelta(days=8))
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-missing-effect-at", clock.current)

        row = await session.get(MemberRotationQuotaOperation, "op-missing-effect-at")
        assert row is not None
        row.remove_requested_at = now.replace(tzinfo=None)
        row.remove_effect = "confirmed"
        row.remove_effect_at = None
        row.completed_at = now.replace(tzinfo=None)
        await session.commit()

        held = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(days=8),
        )
        assert held.count_24h == 1 and held.count_168h == 1


@pytest.mark.asyncio
async def test_confirmed_effect_with_impossible_timestamp_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-invalid-effect-at", now)

        row = await session.get(MemberRotationQuotaOperation, "op-invalid-effect-at")
        assert row is not None
        row.remove_requested_at = (now + timedelta(seconds=1)).replace(tzinfo=None)
        row.remove_effect = "confirmed"
        row.remove_effect_at = (now - timedelta(days=1)).replace(tzinfo=None)
        row.completed_at = (now + timedelta(seconds=2)).replace(tzinfo=None)
        await session.commit()

        held = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(days=8),
        )
        assert held.count_24h == 1 and held.count_168h == 1


@pytest.mark.asyncio
async def test_reservation_returns_only_after_authoritative_non_effect(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-safe", now)
        await repository.record_effect_request("op-safe", effect="remove")

        clock.current = now + timedelta(seconds=1)
        assert not await repository.release_reservation("op-safe")
        clock.current = now + timedelta(seconds=2)
        await repository.record_effect_outcome("op-safe", effect="remove", outcome="authoritative_non_effect")
        clock.current = now + timedelta(seconds=3)
        assert await repository.release_reservation("op-safe")

        snapshot = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(seconds=4),
        )
        assert snapshot.count_24h == 0 and snapshot.count_168h == 0


@pytest.mark.asyncio
async def test_quota_reports_incomplete_local_history_coverage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        snapshot = await RotationQuotaRepository(session, clock=MutableClock(now)).snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now,
        )

        assert snapshot.count_basis == "observed_local"
        assert snapshot.history_complete is False
        assert snapshot.coverage_started_at is None


@pytest.mark.asyncio
async def test_business_completion_is_recorded_without_releasing_quota(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-complete", now)
        await repository.record_effect_request("op-complete", effect="remove")
        clock.current = now + timedelta(seconds=1)
        await repository.record_effect_outcome("op-complete", effect="remove", outcome="confirmed")
        clock.current = now + timedelta(seconds=2)
        completed = await repository.mark_completed("op-complete")

        assert completed.completed_at == (now + timedelta(seconds=2)).replace(tzinfo=None)
        clock.current = now + timedelta(seconds=3)
        assert not await repository.release_reservation("op-complete")
        snapshot = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now + timedelta(seconds=4),
        )
        assert snapshot.count_24h == 1


@pytest.mark.asyncio
async def test_released_reservation_is_terminal_for_stale_workers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-released", now)
        await repository.record_effect_request("op-released", effect="remove")
        clock.current = now + timedelta(seconds=1)
        await repository.record_effect_outcome("op-released", effect="remove", outcome="authoritative_non_effect")
        clock.current = now + timedelta(seconds=2)
        assert await repository.release_reservation("op-released")

        retry = await repository.reserve(
            operation_id="op-released",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
        )
        assert not retry.admitted and retry.code == "reservation_released"
        with pytest.raises(ValueError, match="terminal"):
            await repository.record_effect_request("op-released", effect="remove")


@pytest.mark.asyncio
async def test_admission_uses_authoritative_clock_and_rejects_backdated_bypass(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now)
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-1", now - timedelta(hours=2))
        await _reserve(repository, clock, "op-2", now - timedelta(hours=1))
        await _reserve(repository, clock, "op-3", now)

        clock.current = now + timedelta(minutes=1)
        fourth = await repository.reserve(
            operation_id="op-backdated-attempt",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
        )
        assert not fourth.admitted and fourth.code == "rolling_24h_limit"


@pytest.mark.asyncio
async def test_unfinished_old_reservation_keeps_occupying_quota(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        clock = MutableClock(now - timedelta(days=8))
        repository = RotationQuotaRepository(session, clock=clock)
        await _reserve(repository, clock, "op-still-pending", clock.current)

        snapshot = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=now,
        )
        assert snapshot.count_24h == 1
        assert snapshot.count_168h == 1


@pytest.mark.asyncio
async def test_rotation_event_cannot_bind_to_two_quota_operations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        repository = RotationQuotaRepository(session, clock=MutableClock(now))
        first = await repository.reserve(
            operation_id="op-event-1",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            rotation_event_id="rotation-event-1",
        )
        assert first.admitted

        with pytest.raises(ValueError, match="already bound"):
            await repository.reserve(
                operation_id="op-event-2",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                rotation_event_id="rotation-event-1",
            )


@pytest.mark.asyncio
async def test_same_blocked_event_can_be_admitted_after_window_opens(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    clock = MutableClock(now)
    async with session_factory() as session:
        repository = RotationQuotaRepository(session, clock=clock)
        for index in range(3):
            operation_id = f"seed-{index}"
            effect_base = now - timedelta(hours=1, minutes=index)
            await _reserve(repository, clock, operation_id, effect_base)
            await _confirm_remove(repository, clock, operation_id, effect_base + timedelta(seconds=1))
            clock.current = effect_base + timedelta(seconds=3)
            await repository.mark_completed(operation_id)

        clock.current = now
        blocked = await repository.reserve(
            operation_id="op-deferred",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            rotation_event_id="rotation-event-deferred",
        )
        assert not blocked.admitted and blocked.code == "rolling_24h_limit"
        first_row = await session.get(MemberRotationQuotaOperation, "op-deferred")
        assert first_row is not None and first_row.reserved_at is None
        first_requested_at = first_row.requested_at

        clock.current = now + timedelta(hours=25)
        admitted = await repository.reserve(
            operation_id="op-deferred",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            rotation_event_id="rotation-event-deferred",
        )
        assert admitted.admitted and admitted.code == "admitted"
        row = await session.get(MemberRotationQuotaOperation, "op-deferred", populate_existing=True)
        assert row is not None
        assert row.requested_at == first_requested_at
        assert row.initial_admission_code == "rolling_24h_limit"
        assert row.reserved_at == clock.current.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_concurrent_workspace_admission_allows_only_three(tmp_path) -> None:
    now = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'quota-concurrency.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def reserve(index: int):
        async with factory() as session:
            return await RotationQuotaRepository(session, clock=MutableClock(now)).reserve(
                operation_id=f"concurrent-{index}",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
            )

    try:
        decisions = await asyncio.gather(*(reserve(index) for index in range(4)))
    finally:
        await engine.dispose()

    assert sum(decision.admitted for decision in decisions) == 3
    assert sum(decision.code == "rolling_24h_limit" for decision in decisions) == 1
