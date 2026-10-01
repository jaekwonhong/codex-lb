from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.balancer.recovery import OwnerRecoveryBudget, OwnerRecoveryHint, confirmed_quota_deadline
from app.db.models import AccountStatus

pytestmark = pytest.mark.unit


def at(value: float) -> datetime:
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)


def test_short_wait_is_shared_and_does_not_restart_at_monotonic_zero():
    budget = OwnerRecoveryBudget()
    assert budget.reserve_wait(1.5, now=0, request_remaining=7200) == 1.5
    assert budget.reserve_wait(0.5, now=1.5, request_remaining=7200) == 0.5
    assert budget.started_at == 0
    assert budget.reserve_wait(0.1, now=2, request_remaining=7200) is None
    assert budget.remaining(4) == 1
    assert budget.remaining(5) == 0


@pytest.mark.parametrize("delay", [31.0, 2.01, float("nan"), float("inf"), -1.0])
def test_long_or_invalid_hold_is_not_clipped_into_early_retry(delay):
    budget = OwnerRecoveryBudget()
    assert budget.reserve_wait(delay, now=100, request_remaining=7200) is None
    assert budget.waited_seconds == 0


def test_elapsed_hint_allows_only_one_immediate_retry():
    budget = OwnerRecoveryBudget()
    assert budget.reserve_wait(0, now=100, request_remaining=7200) == 0
    assert budget.reserve_wait(0, now=100, request_remaining=7200) is None


def test_remaining_request_budget_does_not_shorten_real_hold():
    assert OwnerRecoveryBudget().reserve_wait(1.5, now=100, request_remaining=1) is None


def test_new_budget_does_not_time_model_generation():
    budget = OwnerRecoveryBudget()
    assert budget.remaining(7200) == 5
    budget.start(7200)
    assert budget.remaining(7201) == 4


def test_execution_time_is_excluded_without_renewing_recovery_budget():
    budget = OwnerRecoveryBudget()
    budget.reserve_wait(1, now=0, request_remaining=7200)
    budget.pause(2)
    assert budget.engaged
    assert budget.remaining(3602) == 3
    budget.start(3602)
    assert budget.reserve_wait(1, now=3602, request_remaining=3600) == 1
    budget.pause(3603)
    assert budget.remaining(7200) == 2
    assert budget.reserve_wait(0.01, now=7200, request_remaining=60) is None
    assert budget.waited_seconds == 2


def test_hint_preserves_real_reset_and_handles_unknown():
    assert OwnerRecoveryHint("quota_exhausted", 1000).retry_after(100) == 900
    assert OwnerRecoveryHint("unavailable").retry_after(100) is None


def test_fresh_post_block_exhaustion_outlives_local_31_second_hold():
    assert (
        confirmed_quota_deadline(
            status=AccountStatus.RATE_LIMITED,
            blocked_at=100,
            windows=((100.0, 3600, at(135)), (100.0, 7200, at(135))),
            now=140,
            freshness_seconds=60,
        )
        == 7200
    )


@pytest.mark.parametrize(
    "used,reset,observed",
    [
        (99, 3600, 135),
        (100, 139, 135),
        (100, 3600, 99),
        (100, 3600, 100.9),
        (100, 3600, 141),
        (100, 3600, 105),
        (float("nan"), 3600, 135),
    ],
)
def test_unreliable_observation_is_not_recovery_authority(used, reset, observed):
    assert (
        confirmed_quota_deadline(
            status=AccountStatus.RATE_LIMITED,
            blocked_at=100,
            windows=((used, reset, at(observed)),),
            now=140,
            freshness_seconds=30,
        )
        is None
    )


def test_advisory_usage_on_active_account_is_not_fabricated_rejection():
    assert (
        confirmed_quota_deadline(
            status=AccountStatus.ACTIVE,
            blocked_at=100,
            windows=((100.0, 3600, at(135)),),
            now=140,
            freshness_seconds=60,
        )
        is None
    )
