from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
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
    HistoricalUsageConflict,
    MemberUsageSnapshotRepository,
    retained_five_hour_state,
)

pytestmark = pytest.mark.unit

WORKSPACE_ID = "cdp-1"
WORKSPACE_ACCOUNT_ID = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"
PROVENANCE_OBSERVED_AT = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)


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


def _epoch_identity(epoch: str) -> dict[str, str]:
    return {
        "workspace_id": WORKSPACE_ID,
        "workspace_account_id": WORKSPACE_ACCOUNT_ID,
        "account_id": "local-account-1",
        "preset_id": "member-a",
        "email": "member-a@example.com",
        "user_id": "user-MemberA",
        "membership_epoch": epoch,
    }


def _versioned_provenance(**changes: object) -> dict[str, object]:
    provenance: dict[str, object] = {
        "schema_version": 2,
        "five_hour_availability": "observed",
        "evaluation_id": "evaluation-1",
        "workspace_id": WORKSPACE_ID,
        "source_account_id": "local-account-1",
        "source_workspace_account_id": WORKSPACE_ACCOUNT_ID,
        "source_user_id": "user-MemberA",
        "source_email": "member-a@example.com",
        "fetch_id": "fetch-1",
        "requested_workspace_account_id": WORKSPACE_ACCOUNT_ID,
        "account_workspace_id": "metadata-workspace-1",
        "payload_workspace_id": "metadata-workspace-1",
        "credential_source": "stored",
        "started_at": (PROVENANCE_OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        "observed_at": PROVENANCE_OBSERVED_AT.isoformat(),
    }
    provenance.update(changes)
    return provenance


def _provenance_observations(provenance: str, *, weekly_only: bool) -> tuple[FinalUsageSnapshotInput, ...]:
    observations = tuple(replace(item, fetch_provenance=provenance) for item in _observations(PROVENANCE_OBSERVED_AT))
    return observations[1:] if weekly_only else observations


async def _seed_snapshot_epoch(
    session: AsyncSession,
    identity: dict[str, str],
    observations: tuple[FinalUsageSnapshotInput, ...],
) -> None:
    """Represent already committed historical rows without new-input validation."""
    session.add_all(
        [
            WorkspaceMemberFinalUsageSnapshot(
                **identity,
                logical_window=item.logical_window,
                source_window=item.source_window,
                used_percent=item.used_percent,
                reset_at=item.reset_at,
                window_minutes=item.window_minutes,
                observed_at=item.observed_at.replace(tzinfo=None),
                retained_at=PROVENANCE_OBSERVED_AT.replace(tzinfo=None),
                fetch_provenance=item.fetch_provenance,
                fetch_succeeded=item.fetch_succeeded,
                usage_written=item.usage_written,
            )
            for item in observations
        ]
    )
    await session.commit()


@pytest.mark.parametrize("preexisting", [False, True], ids=["new-retention", "existing-history"])
@pytest.mark.parametrize(
    ("provenance", "weekly_only", "expected_state"),
    [
        pytest.param("live_upstream_fetch", False, "observed", id="opaque-text"),
        pytest.param(
            '{"source":"live_upstream_fetch","fetch_id":"legacy-fetch"}',
            False,
            "observed",
            id="opaque-json-object",
        ),
        pytest.param("{}", False, "observed", id="opaque-empty-object"),
        pytest.param('["live_upstream_fetch","legacy-fetch"]', False, "observed", id="opaque-array"),
        pytest.param('"live_upstream_fetch"', False, "observed", id="opaque-json-string"),
        pytest.param('{"schema_version":1,"fetch_id":"legacy-fetch"}', False, "observed", id="explicit-v1"),
        pytest.param(
            json.dumps(
                {
                    key: value
                    for key, value in _versioned_provenance(schema_version=1).items()
                    if key != "five_hour_availability"
                }
            ),
            False,
            "observed",
            id="first-party-v1-shape",
        ),
        pytest.param(json.dumps(_versioned_provenance()), False, "observed", id="v2-observed"),
        pytest.param(
            json.dumps(_versioned_provenance(five_hour_availability="not_provided")),
            True,
            "not_provided",
            id="v2-weekly-only",
        ),
    ],
)
async def test_supported_provenance_preserves_epoch_on_retry_and_new_session_recovery(
    session_factory: async_sessionmaker[AsyncSession],
    provenance: str,
    weekly_only: bool,
    expected_state: str,
    preexisting: bool,
) -> None:
    identity = _epoch_identity("compatible-provenance")
    observations = _provenance_observations(provenance, weekly_only=weekly_only)
    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=lambda: PROVENANCE_OBSERVED_AT)
        if preexisting:
            await _seed_snapshot_epoch(session, identity, observations)
            original = tuple(await repository.list_history())
        else:
            original = await repository.retain_final_snapshots(**identity, observations=observations)
        assert await repository.retain_final_snapshots(**identity, observations=observations) == original
        assert len(original) == (1 if weekly_only else 2)
        assert retained_five_hour_state(original) == expected_state
        assert all(item.fetch_provenance == provenance for item in original)

    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=lambda: PROVENANCE_OBSERVED_AT + timedelta(days=10))
        assert await repository.recover_final_snapshot_epoch(**identity) == original
        assert await repository.retain_final_snapshots(**identity, observations=observations) == original
        changed = tuple(replace(item, used_percent=item.used_percent + 1) for item in observations)
        with pytest.raises(HistoricalUsageConflict):
            await repository.retain_final_snapshots(**identity, observations=changed)
        assert tuple(await repository.list_history()) == original
        assert await repository.recover_final_snapshot_epoch(**identity) == original


async def _assert_provenance_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    provenance: str,
    *,
    weekly_only: bool,
) -> None:
    identity = _epoch_identity("invalid-provenance")
    observations = _provenance_observations(provenance, weekly_only=weekly_only)
    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=lambda: PROVENANCE_OBSERVED_AT)
        with pytest.raises(ValueError):
            await repository.retain_final_snapshots(**identity, observations=observations)
        assert await repository.list_history() == []
        await _seed_snapshot_epoch(session, identity, observations)
        original = await repository.list_history()
        assert retained_five_hour_state(original) == "unknown"

    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=lambda: PROVENANCE_OBSERVED_AT)
        with pytest.raises(HistoricalUsageConflict):
            await repository.recover_final_snapshot_epoch(**identity)
        with pytest.raises(ValueError):
            await repository.retain_final_snapshots(**identity, observations=observations)
        assert await repository.list_history() == original


@pytest.mark.parametrize("weekly_only", [False, True], ids=["complete-pair", "weekly-only"])
@pytest.mark.parametrize(
    "version",
    [None, True, False, 0, -1, 3, 1.0, 2.0, "1", "2", [], {}],
    ids=[
        "null",
        "true",
        "false",
        "zero",
        "negative",
        "future",
        "float-v1",
        "float-v2",
        "text-v1",
        "text-v2",
        "list",
        "dict",
    ],
)
async def test_invalid_explicit_versions_never_use_legacy_fallback(
    session_factory: async_sessionmaker[AsyncSession], version: object, weekly_only: bool
) -> None:
    await _assert_provenance_rejected(
        session_factory,
        json.dumps(
            _versioned_provenance(
                schema_version=version, five_hour_availability="not_provided" if weekly_only else "observed"
            )
        ),
        weekly_only=weekly_only,
    )


@pytest.mark.parametrize("weekly_only", [False, True], ids=["complete-pair", "weekly-only"])
@pytest.mark.parametrize(
    "provenance",
    [
        pytest.param('{"schema_version":2}', id="partial-v2"),
        pytest.param('{"five_hour_availability":"observed"}', id="untagged-observed"),
        pytest.param('{"five_hour_availability":"not_provided"}', id="untagged-absence"),
        pytest.param(
            json.dumps({key: value for key, value in _versioned_provenance().items() if key != "schema_version"}),
            id="v2-missing-schema",
        ),
        pytest.param(
            json.dumps(
                {
                    key: value
                    for key, value in _versioned_provenance().items()
                    if key not in {"schema_version", "five_hour_availability"}
                }
            ),
            id="versioned-binding-missing-tags",
        ),
        pytest.param(
            json.dumps(
                {key: value for key, value in _versioned_provenance().items() if key != "five_hour_availability"}
            ),
            id="v2-missing-availability",
        ),
        pytest.param(json.dumps(_versioned_provenance(schema_version=1)), id="v1-with-observed-availability"),
        pytest.param(
            json.dumps(_versioned_provenance(schema_version=1, five_hour_availability="not_provided")),
            id="v1-with-absence-availability",
        ),
        pytest.param(json.dumps(_versioned_provenance(five_hour_availability="unknown")), id="unknown-availability"),
        pytest.param(json.dumps(_versioned_provenance(five_hour_availability=None)), id="null-availability"),
        pytest.param(json.dumps(_versioned_provenance(five_hour_availability=True)), id="boolean-availability"),
        pytest.param(json.dumps(_versioned_provenance(source_account_id="another-account")), id="v2-wrong-account"),
        pytest.param(
            json.dumps(_versioned_provenance(requested_workspace_account_id="another-workspace")),
            id="v2-wrong-requested-workspace",
        ),
        pytest.param(
            json.dumps(_versioned_provenance(observed_at="2026-09-12T00:00:00Z")), id="v2-wrong-observation-time"
        ),
        pytest.param('{"schema_version":2', id="truncated-versioned-object"),
        pytest.param('{"five_hour_availability":', id="truncated-availability-object"),
        pytest.param('[{"schema_version":2', id="truncated-json-array"),
        pytest.param('{"schema_version":3,"schema_version":1}', id="duplicate-version-fallback"),
        pytest.param(r'{"schema_version":3,"schema_\u0076ersion":1}', id="duplicate-escaped-version"),
        pytest.param(
            json.dumps(_versioned_provenance()).replace(
                '"schema_version": 2', '"schema_version": true, "schema_version": 2'
            ),
            id="duplicate-malformed-version",
        ),
        pytest.param(
            json.dumps(_versioned_provenance()).replace(
                '"five_hour_availability": "observed"',
                '"five_hour_availability": "not_provided", "five_hour_availability": "observed"',
            ),
            id="duplicate-conflicting-availability",
        ),
    ],
)
async def test_partial_malformed_or_conflicting_versioned_provenance_fails_closed(
    session_factory: async_sessionmaker[AsyncSession], provenance: str, weekly_only: bool
) -> None:
    await _assert_provenance_rejected(session_factory, provenance, weekly_only=weekly_only)


@pytest.mark.parametrize(
    ("provenance", "weekly_only"),
    [
        pytest.param("live_upstream_fetch", True, id="opaque-text-weekly-only"),
        pytest.param('{"source":"live_upstream_fetch","fetch_id":"legacy-fetch"}', True, id="opaque-json-weekly-only"),
        pytest.param('{"schema_version":1,"fetch_id":"legacy-fetch"}', True, id="v1-weekly-only"),
        pytest.param(json.dumps(_versioned_provenance()), True, id="v2-observed-without-five-hour"),
        pytest.param(
            json.dumps(_versioned_provenance(five_hour_availability="not_provided")),
            False,
            id="v2-absence-with-five-hour",
        ),
    ],
)
async def test_provenance_never_relaxes_required_window_set(
    session_factory: async_sessionmaker[AsyncSession], provenance: str, weekly_only: bool
) -> None:
    await _assert_provenance_rejected(session_factory, provenance, weekly_only=weekly_only)
