from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.usage.weekly_observation import (
    ClassifiedUsageWindowObservation,
    RotationUsageObservation,
    UsageAccountIdentity,
    UsageFetchProvenance,
)
from app.db.models import Base
from app.modules.member_auth_handoff.rotation_events import RotationQuotaDecision, RotationQuotaRepository
from app.modules.member_auth_handoff.usage_snapshot_repository import MemberUsageSnapshotRepository
from app.modules.member_switch.rotation_foundation import (
    FinalUsageRetentionUnavailable,
    RotationEvaluationIdentity,
    RotationFoundationState,
    RotationQuotaReservationEvidence,
    RotationResetEvidence,
    RotationWeeklyEvidence,
    bind_rotation_reset_resolution,
    bind_rotation_weekly_evidence,
    build_weekly_recovery_observer,
    evaluate_rotation_foundation,
    final_usage_snapshot_inputs,
    reserve_rotation_quota,
)
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditResolution,
    RotationResetCreditResolutionStatus,
    WeeklyRecoveryState,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
WORKSPACE_ID = "workspace-1"
WORKSPACE_ACCOUNT_ID = "workspace-account-1"
MEMBER = UsageAccountIdentity(
    account_id="local-seat-a",
    workspace_account_id=WORKSPACE_ACCOUNT_ID,
    user_id="user-a",
    email="member-a@example.com",
)
EVALUATION = RotationEvaluationIdentity(
    evaluation_id="evaluation-a",
    workspace_id=WORKSPACE_ID,
    member=MEMBER,
    redeem_request_id="reset-request-a",
)


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


def _receipt(
    *,
    weekly_used: float | None = 100.0,
    five_hour_used: float = 45.0,
    observed_at: datetime = NOW,
    weekly_reset_at: int | None = None,
) -> RotationUsageObservation:
    effective_weekly_reset = weekly_reset_at or int((observed_at + timedelta(days=1)).timestamp())
    return RotationUsageObservation(
        fetch_succeeded=True,
        usage_written=False,
        provenance=UsageFetchProvenance(
            fetch_id="fetch-rotation-a",
            identity=MEMBER,
            requested_workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_workspace_id="metadata-workspace-a",
            payload_workspace_id="metadata-workspace-a",
            credential_source="stored",
            started_at=observed_at - timedelta(seconds=1),
            observed_at=observed_at,
        ),
        five_hour_window=ClassifiedUsageWindowObservation(
            source_slot="primary",
            raw_used_percent=five_hour_used,
            window_minutes=300,
            limit_window_seconds=18_000,
            reset_at=int((observed_at + timedelta(hours=1)).timestamp()),
        ),
        weekly_window=ClassifiedUsageWindowObservation(
            source_slot="secondary",
            raw_used_percent=weekly_used,
            window_minutes=10_080,
            limit_window_seconds=604_800,
            reset_at=effective_weekly_reset,
        ),
    )


def _weekly(state: Literal["unknown", "available", "exhausted"] = "exhausted") -> RotationWeeklyEvidence:
    used = {"unknown": None, "available": 50.0, "exhausted": 100.0}[state]
    return bind_rotation_weekly_evidence(
        _receipt(weekly_used=used),
        EVALUATION,
    )


def _reset(status: RotationResetCreditResolutionStatus) -> RotationResetEvidence:
    return bind_rotation_reset_resolution(
        EVALUATION,
        RotationResetCreditResolution(
            status=status,
            redeem_request_id=EVALUATION.redeem_request_id,
            account_id=EVALUATION.member.account_id,
            workspace_account_id=EVALUATION.workspace_account_id,
        ),
    )


async def _reserve_at(
    repository: RotationQuotaRepository,
    clock: MutableClock,
    *,
    operation_id: str,
    at: datetime,
):
    clock.current = at
    decision = await repository.reserve(
        operation_id=operation_id,
        workspace_id=WORKSPACE_ID,
        workspace_account_id=WORKSPACE_ACCOUNT_ID,
    )
    return RotationQuotaReservationEvidence(
        evaluation=EVALUATION,
        operation_id=operation_id,
        decision=decision,
    )


async def _complete_effective_rotation(
    repository: RotationQuotaRepository,
    clock: MutableClock,
    operation_id: str,
    at: datetime,
) -> None:
    clock.current = at
    await repository.record_effect_request(operation_id, effect="remove")
    clock.current = at + timedelta(seconds=1)
    await repository.record_effect_outcome(operation_id, effect="remove", outcome="confirmed")
    clock.current = at + timedelta(seconds=2)
    await repository.mark_completed(operation_id)


async def test_p1_to_p2_adapter_rechecks_identity_and_fetch_boundary() -> None:
    receipt = _receipt()

    async def fetch_usage() -> RotationUsageObservation:
        return receipt

    current_member = MEMBER

    async def resolve_member() -> UsageAccountIdentity:
        return current_member

    observer = build_weekly_recovery_observer(
        fetch_usage,
        resolve_member,
        evaluation=EVALUATION,
        not_before=NOW - timedelta(seconds=2),
        clock=lambda: NOW,
    )
    assert await observer() is WeeklyRecoveryState.EXHAUSTED

    current_member = replace(MEMBER, user_id="replacement-user")
    assert await observer() is WeeklyRecoveryState.UNKNOWN

    too_new_boundary = build_weekly_recovery_observer(
        fetch_usage,
        resolve_member,
        evaluation=EVALUATION,
        not_before=NOW,
        clock=lambda: NOW,
    )
    assert await too_new_boundary() is WeeklyRecoveryState.UNKNOWN

    exact = bind_rotation_weekly_evidence(receipt, EVALUATION)
    assert exact.assess(MEMBER, now=NOW).state == "exhausted"


def test_reset_recovery_and_unresolved_reset_never_reach_admission() -> None:
    exhausted = _weekly()

    recovered = evaluate_rotation_foundation(
        exhausted,
        current_member=MEMBER,
        now=NOW,
        reset=_reset(RotationResetCreditResolutionStatus.USAGE_RECOVERED),
    )
    assert recovered.state is RotationFoundationState.RESET_RECOVERED
    assert not recovered.admission_ready

    pending = evaluate_rotation_foundation(
        exhausted,
        current_member=MEMBER,
        now=NOW,
        reset=_reset(RotationResetCreditResolutionStatus.RECONCILIATION_PENDING),
    )
    assert pending.state is RotationFoundationState.RESET_RECONCILIATION_PENDING
    assert pending.attention_required and not pending.admission_ready

    unavailable = evaluate_rotation_foundation(
        exhausted,
        current_member=MEMBER,
        now=NOW,
        reset=_reset(RotationResetCreditResolutionStatus.UNAVAILABLE),
    )
    assert unavailable.state is RotationFoundationState.RESET_UNAVAILABLE
    assert unavailable.attention_required and not unavailable.admission_ready


async def test_confirmed_no_credit_allows_exact_third_and_seventh_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        clock = MutableClock(NOW)
        repository = RotationQuotaRepository(session, clock=clock)
        for index, age in enumerate(
            (
                timedelta(days=6),
                timedelta(days=5),
                timedelta(days=4),
                timedelta(days=3),
                timedelta(hours=2),
                timedelta(hours=1),
            ),
            start=1,
        ):
            evidence = await _reserve_at(
                repository,
                clock,
                operation_id=f"prior-{index}",
                at=NOW - age,
            )
            assert evidence.decision.admitted
            await _complete_effective_rotation(
                repository,
                clock,
                evidence.operation_id,
                NOW - age + timedelta(seconds=1),
            )

        clock.current = NOW
        quota = await reserve_rotation_quota(
            repository,
            weekly=_weekly(),
            reset=_reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT),
            current_member=MEMBER,
            now=NOW,
            operation_id="new-op",
        )
        decision = evaluate_rotation_foundation(
            _weekly(),
            current_member=MEMBER,
            now=NOW,
            reset=_reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT),
            quota=quota,
        )

        assert quota.decision.count_24h == 3
        assert quota.decision.count_168h == 7
        assert decision.state is RotationFoundationState.ADMISSION_READY
        assert decision.admission_ready


async def test_quota_full_blocks_foundation_admission(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        clock = MutableClock(NOW)
        repository = RotationQuotaRepository(session, clock=clock)
        for index, age in enumerate((3, 2, 1), start=1):
            evidence = await _reserve_at(
                repository,
                clock,
                operation_id=f"full-{index}",
                at=NOW - timedelta(hours=age),
            )
            assert evidence.decision.admitted
            await _complete_effective_rotation(
                repository,
                clock,
                evidence.operation_id,
                NOW - timedelta(hours=age) + timedelta(seconds=1),
            )

        clock.current = NOW
        blocked = await reserve_rotation_quota(
            repository,
            weekly=_weekly(),
            reset=_reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT),
            current_member=MEMBER,
            now=NOW,
            operation_id="blocked",
        )
        decision = evaluate_rotation_foundation(
            _weekly(),
            current_member=MEMBER,
            now=NOW,
            reset=_reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT),
            quota=blocked,
        )

        assert not blocked.decision.admitted
        assert blocked.decision.code == "rolling_24h_limit"
        assert decision.state is RotationFoundationState.QUOTA_BLOCKED
        assert not decision.admission_ready


def test_foundation_rejects_cross_evaluation_reset_and_quota_evidence() -> None:
    foreign_member = replace(
        MEMBER,
        account_id="local-seat-b",
        workspace_account_id="workspace-account-2",
        user_id="user-b",
        email="member-b@example.com",
    )
    foreign = RotationEvaluationIdentity(
        evaluation_id="evaluation-b",
        workspace_id="workspace-2",
        member=foreign_member,
        redeem_request_id="reset-request-b",
    )
    foreign_reset = RotationResetEvidence(
        evaluation=foreign,
        resolution=RotationResetCreditResolution(
            status=RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT,
            redeem_request_id=foreign.redeem_request_id,
            account_id=foreign.member.account_id,
            workspace_account_id=foreign.workspace_account_id,
        ),
    )
    foreign_quota = RotationQuotaReservationEvidence(
        evaluation=foreign,
        operation_id="foreign-op",
        decision=RotationQuotaDecision(
            admitted=True,
            code="admitted",
            count_24h=1,
            count_168h=1,
        ),
    )

    mixed_reset = evaluate_rotation_foundation(
        _weekly(),
        current_member=MEMBER,
        now=NOW,
        reset=foreign_reset,
    )
    mixed_quota = evaluate_rotation_foundation(
        _weekly(),
        current_member=MEMBER,
        now=NOW,
        reset=_reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT),
        quota=foreign_quota,
    )

    assert mixed_reset.state is RotationFoundationState.INVALID_EVIDENCE
    assert mixed_reset.attention_required and not mixed_reset.admission_ready
    assert mixed_quota.state is RotationFoundationState.INVALID_EVIDENCE
    assert mixed_quota.attention_required and not mixed_quota.admission_ready

    same_request_foreign_account = RotationResetCreditResolution(
        status=RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT,
        redeem_request_id=EVALUATION.redeem_request_id,
        account_id=foreign.member.account_id,
        workspace_account_id=foreign.workspace_account_id,
    )
    with pytest.raises(ValueError, match="identity does not match"):
        bind_rotation_reset_resolution(EVALUATION, same_request_foreign_account)


def test_reset_pending_remains_attention_even_if_weekly_looks_available() -> None:
    decision = evaluate_rotation_foundation(
        _weekly("available"),
        current_member=MEMBER,
        now=NOW,
        reset=_reset(RotationResetCreditResolutionStatus.RECONCILIATION_PENDING),
    )
    assert decision.state is RotationFoundationState.RESET_RECONCILIATION_PENDING
    assert decision.attention_required and not decision.admission_ready


async def test_quota_reservation_rejects_reset_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repository = RotationQuotaRepository(session, clock=lambda: NOW)
        with pytest.raises(ValueError, match="prerequisites"):
            await reserve_rotation_quota(
                repository,
                weekly=_weekly(),
                reset=_reset(RotationResetCreditResolutionStatus.RECONCILIATION_PENDING),
                current_member=MEMBER,
                now=NOW,
                operation_id="pending-reset-op",
            )
        snapshot = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=NOW,
        )
        assert snapshot.count_24h == 0 and snapshot.count_168h == 0


async def test_weekly_evidence_is_reassessed_at_final_admission_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    short_lived = bind_rotation_weekly_evidence(
        _receipt(weekly_reset_at=int((NOW + timedelta(seconds=1)).timestamp())),
        EVALUATION,
    )
    reset = _reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT)
    async with session_factory() as session:
        repository = RotationQuotaRepository(session, clock=lambda: NOW)
        quota = await reserve_rotation_quota(
            repository,
            weekly=short_lived,
            reset=reset,
            current_member=MEMBER,
            now=NOW,
            operation_id="short-lived-weekly",
        )
        assert quota.decision.admitted

        expired = evaluate_rotation_foundation(
            short_lived,
            current_member=MEMBER,
            now=NOW + timedelta(seconds=2),
            reset=reset,
            quota=quota,
        )
        assert expired.state is RotationFoundationState.USAGE_UNKNOWN
        assert expired.weekly_reason == "reset_elapsed"
        assert expired.attention_required and not expired.admission_ready


async def test_unknown_effect_reservation_survives_until_authoritative_non_effect(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        clock = MutableClock(NOW)
        repository = RotationQuotaRepository(session, clock=clock)
        reserved = await _reserve_at(repository, clock, operation_id="unknown-remove", at=NOW)
        assert reserved.decision.admitted
        await repository.record_effect_request(reserved.operation_id, effect="remove")

        clock.current = NOW + timedelta(days=8)
        held = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=clock.current,
        )
        assert held.count_24h == 1 and held.count_168h == 1
        assert not await repository.release_reservation(reserved.operation_id)

        await repository.record_effect_outcome(
            reserved.operation_id,
            effect="remove",
            outcome="authoritative_non_effect",
        )
        assert await repository.release_reservation(reserved.operation_id)
        released = await repository.snapshot(
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            observed_at=clock.current,
        )
        assert released.count_24h == 0 and released.count_168h == 0


async def test_same_fetch_final_usage_retention_is_immutable_across_account_reuse(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inputs = final_usage_snapshot_inputs(_receipt(), EVALUATION, MEMBER, now=NOW)
    assert inputs[0].fetch_provenance == inputs[1].fetch_provenance
    assert inputs[0].logical_window == "5h" and inputs[1].logical_window == "weekly"

    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=lambda: NOW)
        with pytest.raises(ValueError, match="source identity mismatch"):
            await repository.retain_final_snapshots(
                workspace_id="workspace-other",
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                account_id=MEMBER.account_id,
                preset_id="member-a",
                email=MEMBER.email,
                user_id=MEMBER.user_id or "",
                membership_epoch="wrong-workspace",
                observations=inputs,
            )
        first = await repository.retain_final_snapshots(
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_id=MEMBER.account_id,
            preset_id="member-a",
            email=MEMBER.email,
            user_id=MEMBER.user_id or "",
            membership_epoch="epoch-1",
            observations=inputs,
        )

        replacement_receipt = _receipt(weekly_used=88, five_hour_used=22)
        replacement_inputs = final_usage_snapshot_inputs(replacement_receipt, EVALUATION, MEMBER, now=NOW)
        second = await repository.retain_final_snapshots(
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_id=MEMBER.account_id,
            preset_id="member-a",
            email=MEMBER.email,
            user_id=MEMBER.user_id or "",
            membership_epoch="epoch-2",
            observations=replacement_inputs,
        )
        history = await repository.list_history(workspace_account_id=WORKSPACE_ACCOUNT_ID)

        assert first[0].used_percent == 45.0 and first[1].used_percent == 100.0
        assert second[0].used_percent == 22.0 and second[1].used_percent == 88.0
        assert [row.used_percent for row in history if row.membership_epoch == "epoch-1"] == [45.0, 100.0]


async def test_historical_reset_invalidation_preserves_original_same_fetch_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inputs = final_usage_snapshot_inputs(_receipt(), EVALUATION, MEMBER, now=NOW)
    async with session_factory() as session:
        repository = MemberUsageSnapshotRepository(session, clock=lambda: NOW)
        retained = await repository.retain_final_snapshots(
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_id=MEMBER.account_id,
            preset_id="member-a",
            email=MEMBER.email,
            user_id=MEMBER.user_id or "",
            membership_epoch="epoch-before-cutoff",
            observations=inputs,
        )
        original = [(row.used_percent, row.reset_at, row.fetch_provenance) for row in retained]

        invalidation = await repository.invalidate_historical_reset_schedules(cutoff_at=NOW)
        after = await repository.list_history(workspace_account_id=WORKSPACE_ACCOUNT_ID)

        assert invalidation.affected_count == 2
        assert [(row.used_percent, row.reset_at, row.fetch_provenance) for row in after] == original
        assert all(row.effective_reset_at is None for row in after)


@pytest.mark.parametrize(
    ("receipt", "code"),
    [
        (replace(_receipt(), five_hour_window=None), "five_hour_missing"),
        (replace(_receipt(), fetch_succeeded=False), "fetch_failed"),
        (
            replace(
                _receipt(),
                provenance=replace(
                    cast(UsageFetchProvenance, _receipt().provenance),
                    identity=replace(MEMBER, user_id="old-user"),
                ),
            ),
            "identity_mismatch",
        ),
    ],
)
def test_final_usage_retention_fails_closed_without_exact_same_fetch_evidence(
    receipt: RotationUsageObservation,
    code: str,
) -> None:
    with pytest.raises(FinalUsageRetentionUnavailable) as exc_info:
        final_usage_snapshot_inputs(receipt, EVALUATION, MEMBER, now=NOW)
    assert exc_info.value.code == code
