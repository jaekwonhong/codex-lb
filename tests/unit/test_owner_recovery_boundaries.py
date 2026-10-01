from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.core.balancer import AccountState, select_account
from app.core.balancer.recovery import OwnerRecoveryBudget
from app.core.clients.proxy import ProxyResponseError
from app.core.errors import openai_error
from app.db.models import AccountStatus
from app.modules.proxy._load_balancer.types import RuntimeState
from app.modules.proxy._service.http_bridge.helpers import (
    _http_bridge_previous_response_owner_unavailable_error,
    _http_bridge_reconnect_connect_failure,
)
from app.modules.proxy._service.http_bridge.streaming import _http_bridge_capacity_wait_plan
from app.modules.proxy._service.support import _sleep_for_account_selection_recovery, _WebSocketRequestState
from app.modules.proxy.helpers import _apply_error_metadata, _parse_openai_error
from app.modules.proxy.load_balancer import AccountSelection, _state_from_account
from app.modules.proxy.owner_recovery import owner_pressure_hint, turn_is_unsubmitted
from app.modules.proxy.service import ProxyService
from tests.simulation.virtual_time import VirtualClock, VirtualScheduler
from tests.unit.test_load_balancer import _epoch_to_naive_utc, _make_test_account, _make_test_usage
from tests.unit.test_proxy_http_bridge import _make_bridge_session

pytestmark = pytest.mark.unit


def request_state(budget=None):
    state = _WebSocketRequestState(
        request_id="owner-recovery-test",
        model="gpt-6-astra",
        service_tier=None,
        reasoning_effort="xhigh",
        api_key_reservation=None,
        started_at=0,
    )
    if budget is not None:
        state.owner_recovery_budget = budget
    return state


def test_real_state_builder_does_not_recover_from_only_expired_default_hold():
    now = 1_700_000_140.0
    blocked = int(now - 40)
    account = _make_test_account(status=AccountStatus.RATE_LIMITED, blocked_at=blocked, reset_at=blocked + 31)
    primary = _make_test_usage(
        window="primary",
        used_percent=100,
        reset_at=int(now + 3600),
        recorded_at=_epoch_to_naive_utc(now - 5),
    )
    state = _state_from_account(
        account=account, primary_entry=primary, secondary_entry=None, runtime=RuntimeState(), now=now
    )
    result = select_account([state], now=now, allow_usage_exhaustion_error=False)
    assert result.account is None
    assert result.resets_at == now + 3600
    assert state.status == AccountStatus.RATE_LIMITED
    # Evaluation did not mutate the persisted ORM row or usage sample.
    assert account.reset_at == blocked + 31
    assert primary.used_percent == 100


@pytest.mark.parametrize("credits", [False, True])
def test_long_window_evidence_respects_existing_credit_override(credits):
    now = 1_700_000_140.0
    account = _make_test_account(status=AccountStatus.QUOTA_EXCEEDED, blocked_at=int(now - 140), reset_at=int(now - 1))
    secondary = _make_test_usage(
        used_percent=100, reset_at=int(now + 3600), recorded_at=_epoch_to_naive_utc(now - 5), credits_has=credits
    )
    state = _state_from_account(
        account=account, primary_entry=None, secondary_entry=secondary, runtime=RuntimeState(), now=now
    )
    assert state.status == (AccountStatus.ACTIVE if credits else AccountStatus.QUOTA_EXCEEDED)


def test_owner_error_preserves_original_horizon_not_wait_budget():
    selection = AccountSelection(None, "Usage limit reached", "usage_limit_reached", resets_at=1100)
    exc = _http_bridge_previous_response_owner_unavailable_error(selection, now=1000)
    assert exc.retry_after_seconds == 100
    assert exc.payload["error"]["resets_at"] == 1100
    assert "usage_limit_reached" in exc.payload["error"]["message"]


def test_reset_hint_keeps_longest_constraint_on_the_same_owner():
    state = AccountState("owner", AccountStatus.RATE_LIMITED, reset_at=1031, cooldown_until=1001)
    result = select_account([state], now=1000, allow_usage_exhaustion_error=False)
    assert result.account is None
    assert result.resets_at == 1031


def test_owner_advice_preserves_real_quota_reset_before_default_hold_expires():
    state = AccountState(
        "owner",
        AccountStatus.RATE_LIMITED,
        used_percent=100,
        reset_at=1031,
        primary_reset_at=4600,
        cooldown_until=1001,
    )
    hint = owner_pressure_hint(state, now=1000, primary_threshold=95, secondary_threshold=100, fresh_usage=True)
    assert hint is not None
    assert hint.reason == "quota_exhausted"
    assert hint.retry_at == 4600


def test_leased_work_is_not_misreported_as_confirmed_quota_exhaustion():
    state = AccountState(
        "owner",
        AccountStatus.RATE_LIMITED,
        used_percent=100,
        priority_used_percent=85,
        reset_at=1031,
        primary_reset_at=4600,
    )
    hint = owner_pressure_hint(state, now=1000, primary_threshold=95, secondary_threshold=100, fresh_usage=True)
    assert hint is not None
    assert hint.reason == "cooldown"
    assert hint.retry_at == 1031


def test_auth_error_is_not_rewritten_as_transient_owner_error():
    original = ProxyResponseError(401, openai_error("token_revoked", "Credentials require reauthentication"))
    assert _http_bridge_reconnect_connect_failure(original, "owner") is original


def test_error_metadata_preserves_owner_reason_and_horizon_for_stream_frames():
    error = _http_bridge_previous_response_owner_unavailable_error(
        AccountSelection(None, "Owner unavailable", "usage_limit_reached", 4600), now=1000
    )
    target = {}
    _apply_error_metadata(target, _parse_openai_error(error.payload))
    assert target == {
        "availability_reason": "usage_limit_reached",
        "resets_at": 4600,
        "resets_in_seconds": 3600,
    }


@pytest.mark.asyncio
async def test_real_owner_wait_respects_short_hint_and_shares_nested_budget():
    clock = VirtualClock()
    scheduler = VirtualScheduler(clock)
    budget = OwnerRecoveryBudget()
    state = request_state(budget)
    selection = AccountSelection(
        None, "Owner recovering", "continuity_owner_unavailable", resets_at=int(clock.time() + 1)
    )
    task = scheduler.create_task(
        _sleep_for_account_selection_recovery(
            selection,
            request_id="r",
            kind="websocket",
            request_stage="reattach",
            model="gpt-6-astra",
            max_sleep_seconds=7200,
            request_state=state,
            scheduler=scheduler,
            clock=clock,
        )
    )
    await scheduler.advance(1)
    assert await task
    assert state.account_capacity_waiting is False
    rebuilt = request_state(budget)
    selection.resets_at = int(clock.time() + 2)
    assert not await _sleep_for_account_selection_recovery(
        selection,
        request_id="r",
        kind="http_bridge",
        request_stage="reattach",
        model="gpt-6-astra",
        max_sleep_seconds=7200,
        request_state=rebuilt,
        scheduler=scheduler,
        clock=clock,
    )
    assert clock.monotonic() == 1


@pytest.mark.asyncio
async def test_long_owner_wait_is_refused_without_early_retry():
    clock = VirtualClock()
    scheduler = VirtualScheduler(clock)
    assert not await _sleep_for_account_selection_recovery(
        AccountSelection(None, "Owner recovering", "continuity_owner_unavailable", int(clock.time() + 31)),
        request_id="r",
        kind="http_bridge",
        request_stage="reattach",
        model="gpt-6-astra",
        max_sleep_seconds=7200,
        request_state=request_state(),
        scheduler=scheduler,
        clock=clock,
    )
    assert clock.monotonic() == 0


@pytest.mark.asyncio
async def test_cancel_owner_wait_clears_wait_state():
    clock = VirtualClock()
    scheduler = VirtualScheduler(clock)
    state = request_state()
    task = scheduler.create_task(
        _sleep_for_account_selection_recovery(
            AccountSelection(None, "Owner recovering", "hard_affinity_saturated", int(clock.time() + 2)),
            request_id="r",
            kind="websocket",
            request_stage="reattach",
            model="gpt-6-astra",
            max_sleep_seconds=7200,
            request_state=state,
            scheduler=scheduler,
            clock=clock,
        )
    )
    await scheduler.drain()
    assert state.account_capacity_waiting
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not state.account_capacity_waiting
    assert state.account_capacity_wait_retry_after_seconds is None
    await scheduler.cancel_owned_tasks()


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_create_sent_at", 0.0),
        ("response_create_attempt_count", 1),
        ("response_id", "resp_created"),
        ("response_event_count", 1),
        ("last_downstream_sequence_number", 1),
        ("downstream_visible", True),
        ("operation_registered", True),
        ("operation_dispatched", True),
        ("recovery_attempt_dispatched", True),
        ("operation_persisted_response_id", "resp_stored"),
        ("replay_downstream_response_id", "resp_replay"),
        ("payload_conversation_bound", True),
        ("request_kind", "prewarm"),
    ],
)
def test_uncertain_or_accepted_turn_is_never_preemptible(field, value):
    state = request_state()
    assert turn_is_unsubmitted(state)
    setattr(state, field, value)
    assert not turn_is_unsubmitted(state)


def test_headroom_requires_fresh_applicable_usage():
    state = AccountState("owner", AccountStatus.ACTIVE, used_percent=96)
    args = dict(now=1000, primary_threshold=95, secondary_threshold=100)
    assert owner_pressure_hint(state, fresh_usage=True, **args).reason == "headroom"
    assert owner_pressure_hint(state, fresh_usage=False, **args) is None
    assert owner_pressure_hint(replace(state, ignore_standard_quota=True), fresh_usage=True, **args) is None


def test_optimistic_preparation_flag_does_not_claim_upstream_acceptance():
    state = request_state()
    state.awaiting_response_created = True
    assert turn_is_unsubmitted(state)


def test_nested_capacity_wait_cannot_renew_owner_wait_budget():
    budget = OwnerRecoveryBudget()
    budget.reserve_wait(2, now=0, request_remaining=7200)
    error = ProxyResponseError(429, openai_error("rate_limit_exceeded", "Try again in 1s"))
    assert _http_bridge_capacity_wait_plan(error, request_deadline=7200, now=2, owner_recovery_budget=budget) is None


@pytest.mark.asyncio
async def test_real_submit_cancels_only_control_before_dispatch_at_five_seconds(monkeypatch):
    clock = VirtualClock()
    scheduler = VirtualScheduler(clock)
    service = ProxyService(cast(Any, nullcontext()), clock=clock, scheduler=scheduler)
    session = _make_bridge_session(key_value="owner-recovery-deadline")
    state = request_state()
    state.owner_recovery_budget.start(0)
    cancelled = []

    async def delayed_admission(*args, **kwargs):
        try:
            await scheduler.sleep(30)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(service, "_submit_http_bridge_request_with_handoff", delayed_admission)
    cleanup = AsyncMock(return_value=False)
    monkeypatch.setattr(service, "_release_http_bridge_admission_preregistration", cleanup)
    task = scheduler.create_task(
        service._submit_http_bridge_request(
            session,
            request_state=state,
            text_data='{"type":"response.create"}',
            queue_limit=4,
        )
    )
    await scheduler.advance(5)
    with pytest.raises(ProxyResponseError) as error:
        await task
    assert error.value.payload["error"]["code"] == "owner_recovery_budget_exhausted"
    assert state.response_create_attempt_count == 0
    assert cancelled == [True]
    cleanup.assert_awaited_once()
    await scheduler.cancel_owned_tasks()
