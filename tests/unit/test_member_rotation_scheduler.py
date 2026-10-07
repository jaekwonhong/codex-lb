from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, select

from app.db.models import Account, MemberRotationQuotaOperation, MemberRotationWorkspaceControl
from app.modules.member_rotation_operator.repository import MemberRotationOperatorRepository
from app.modules.member_switch.rotation_controller import RotationController
from app.modules.member_switch.rotation_plan import SCHEDULE_BINDING_ID, CanaryPlan
from app.modules.member_switch.rotation_scheduler import RotationScheduler
from app.modules.member_switch.rotation_worker import RotationWorker, WorkerServices
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditResolution,
    RotationResetCreditResolutionStatus,
)
from tests.unit.test_member_rotation_controller import (
    NOW,
    OUTGOING,
    WORKSPACE_ACCOUNT_ID,
    WORKSPACE_ID,
    SyntheticRuntimeAttestation,
    p4_provenance,
    receipt,
)
from tests.unit.test_member_rotation_controller import (
    rotation_context as rotation_context,
)

pytestmark = pytest.mark.unit


def plan():
    assert OUTGOING.user_id is not None
    return CanaryPlan(
        enabled=True,
        evaluation_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        workspace_account_id=WORKSPACE_ACCOUNT_ID,
        outgoing_account_id=OUTGOING.account_id,
        outgoing_email=OUTGOING.email,
        outgoing_user_id=OUTGOING.user_id,
        membership_epoch="synthetic-membership",
        expires_at=NOW + timedelta(minutes=5),
        provenance=p4_provenance(),
    )


async def immediate_leader(body):
    await body()


async def test_default_off_does_not_even_elect_leader(tmp_path):
    async def unexpected(*_):
        pytest.fail("OFF must not touch DB, leader or effect worker")

    scheduler = RotationScheduler(tmp_path, unexpected, leader=unexpected)
    await scheduler.tick()
    (tmp_path / "canary-plan.json").write_text(plan().model_copy(update={"enabled": False}).model_dump_json())
    await scheduler.tick()
    await scheduler.start()
    await scheduler.start()
    await asyncio.sleep(0)
    await scheduler.stop()
    assert scheduler._task is None


async def test_wmc_writer_mode_makes_scheduler_inert_even_with_valid_plan(tmp_path, monkeypatch):
    selected = plan()
    (tmp_path / "canary-plan.json").write_text(selected.model_dump_json())

    async def unexpected(*_):
        pytest.fail("WMC writer mode must not elect leader or execute a legacy plan")

    monkeypatch.setattr(
        "app.modules.member_switch.rotation_scheduler.get_settings",
        lambda: SimpleNamespace(workspace_membership_writer="wmc"),
    )
    scheduler = RotationScheduler(tmp_path, unexpected, leader=unexpected, clock=lambda: NOW)
    await scheduler.tick()


async def test_stop_cancels_and_awaits_active_worker(tmp_path):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    (tmp_path / "canary-plan.json").write_text(plan().model_dump_json())

    async def execute(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    scheduler = RotationScheduler(tmp_path, execute, leader=immediate_leader, clock=lambda: NOW)
    await scheduler.start()
    await asyncio.wait_for(entered.wait(), 1)
    await scheduler.stop()
    assert cancelled.is_set()


@pytest_asyncio.fixture
async def worker_context(rotation_context, tmp_path, monkeypatch):
    _, switch, controls, companion, sessions, clock = rotation_context
    async with sessions() as session:
        connection = await session.connection()
        await connection.run_sync(lambda conn: cast(Table, MemberRotationWorkspaceControl.__table__).create(conn))
        session.add(
            Account(
                id=OUTGOING.account_id,
                email=OUTGOING.email,
                chatgpt_account_id=WORKSPACE_ACCOUNT_ID,
                chatgpt_user_id=OUTGOING.user_id,
                plan_type="team",
                access_token_encrypted=b"synthetic",
                refresh_token_encrypted=b"synthetic",
                id_token_encrypted=b"synthetic",
                last_refresh=NOW,
            )
        )
        await session.commit()
        await MemberRotationOperatorRepository(session).set_intent(
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            enabled=True,
            expected_version=0,
        )
    selected = plan()
    (tmp_path / "canary-plan.json").write_text(selected.model_dump_json())
    runtime = SyntheticRuntimeAttestation(clock)
    state = SimpleNamespace(fetches=0, resets=0, used=100.0, recover=False, interrupt=False, disable=False)

    class Usage:
        async def force_rotation_usage_observation(self, account):
            state.fetches += 1
            original = receipt(weekly_used=state.used)
            assert original.provenance is not None
            return replace(original, provenance=replace(original.provenance, started_at=clock(), observed_at=clock()))

        async def force_refresh_result(self, account):
            return SimpleNamespace(fetch_succeeded=True)

    @asynccontextmanager
    async def services(runtime, guard):
        yield WorkerServices(
            RotationController(
                controls,
                switch,
                sessions,
                sessions,
                clock=clock,
                runtime_attestation=runtime,
                dispatch_guard=guard,
            ),
            Usage(),
        )

    async def reset(account, **kwargs):
        state.resets += 1
        assert await controls.get(SCHEDULE_BINDING_ID) is not None
        if state.interrupt:
            raise RuntimeError("synthetic crash after durable evaluation admission")
        if state.disable:
            (tmp_path / "canary-plan.json").unlink()
        if state.recover:
            state.used = 20.0
        return RotationResetCreditResolution(
            status=(
                RotationResetCreditResolutionStatus.USAGE_RECOVERED
                if state.recover
                else RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT
            ),
            redeem_request_id=kwargs["redeem_request_id"],
            account_id=account.id,
            workspace_account_id=account.chatgpt_account_id,
        )

    monkeypatch.setattr("app.modules.member_switch.rotation_worker.resolve_rotation_reset_credit", reset)
    worker = RotationWorker(tmp_path, sessions=sessions, services=services, runtime=runtime, clock=clock)
    return worker, selected, state, companion, controls, sessions


async def test_full_scheduler_path_and_restart_do_not_repeat_reset_or_start(worker_context):
    worker, selected, state, companion, controls, _ = worker_context
    scheduler = RotationScheduler(worker.directory, worker.run, leader=immediate_leader, clock=worker.clock)
    await asyncio.gather(scheduler.tick(), scheduler.tick())
    assert state.resets == 1 and companion.start_calls == 1
    restarted = RotationWorker(
        worker.directory, sessions=worker.sessions, services=worker.services, runtime=worker.runtime, clock=worker.clock
    )
    await restarted.run(selected)
    assert state.resets == 1 and companion.start_calls == 1
    assert await controls.get(SCHEDULE_BINDING_ID) is not None


async def test_wmc_writer_mode_fences_direct_legacy_worker_before_effect(worker_context, monkeypatch):
    worker, selected, state, companion, controls, _ = worker_context
    monkeypatch.setattr(
        "app.modules.member_switch.rotation_worker.get_settings",
        lambda: SimpleNamespace(
            workspace_membership_writer="wmc",
            companion_account_pool_url=None,
        ),
    )

    with pytest.raises(ValueError, match="workspace_membership_writer_moved"):
        await worker.run(selected)

    assert state.fetches == 0
    assert state.resets == 0
    assert companion.start_calls == 0
    assert await controls.get(SCHEDULE_BINDING_ID) is None


async def test_recovery_consumes_no_membership_or_quota(worker_context):
    worker, selected, state, companion, _, sessions = worker_context
    state.recover = True
    await worker.run(selected)
    await worker.run(selected)
    assert state.resets == 1 and companion.start_calls == 0
    async with sessions() as session:
        assert not list((await session.scalars(select(MemberRotationQuotaOperation))).all())


@pytest.mark.parametrize("change", ["expire", "revoke"])
async def test_plan_change_during_final_intent_query_blocks_dispatch(worker_context, monkeypatch, change):
    worker, selected, state, companion, _, sessions = worker_context
    original_quota = RotationController._quota_request
    original_intent = MemberRotationOperatorRepository.intent
    dispatch = False

    async def mark_dispatch(self, *args):
        nonlocal dispatch
        await original_quota(self, *args)
        dispatch = True

    async def delayed_intent(self, **kwargs):
        intent = await original_intent(self, **kwargs)
        if dispatch:
            if change == "expire":
                worker.clock.current = selected.expires_at
            else:
                (worker.directory / "canary-plan.json").unlink(missing_ok=True)
        return intent

    monkeypatch.setattr(RotationController, "_quota_request", mark_dispatch)
    monkeypatch.setattr(MemberRotationOperatorRepository, "intent", delayed_intent)
    await worker.run(selected)
    assert state.resets == 1 and companion.start_calls == 0
    async with sessions() as session:
        row = (await session.scalars(select(MemberRotationQuotaOperation))).one()
        assert row.remove_effect == "authoritative_non_effect"
        assert row.reservation_released_at is not None


async def test_two_worker_instances_cannot_spend_another_evaluation(worker_context):
    worker, selected, state, companion, _, _ = worker_context
    peer = RotationWorker(
        worker.directory, sessions=worker.sessions, services=worker.services, runtime=worker.runtime, clock=worker.clock
    )
    results = await asyncio.gather(worker.run(selected), peer.run(selected), return_exceptions=True)
    assert any(result is None for result in results)
    assert state.resets == 1 and companion.start_calls == 1


@pytest.mark.parametrize("kind", ["available", "disabled_intent", "old_companion", "disable_after_reset", "crash"])
async def test_worker_blocks_without_replay(worker_context, monkeypatch, kind):
    worker, selected, state, companion, controls, sessions = worker_context
    if kind == "available":
        state.used = 20.0
        await worker.run(selected)
        assert state.resets == 0 and await controls.get(SCHEDULE_BINDING_ID) is None
    elif kind == "disabled_intent":
        async with sessions() as session:
            await MemberRotationOperatorRepository(session).set_intent(
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                enabled=False,
                expected_version=1,
            )
        with pytest.raises(ValueError, match="workspace_disabled"):
            await worker.run(selected)
        assert state.fetches == 0
    elif kind == "old_companion":
        original = companion.catalog

        async def old():
            return (await original()).model_copy(
                update={
                    "capabilities": [
                        c for c in (await original()).capabilities if c != "member_rotation_canary_effect_gate_v1"
                    ]
                }
            )

        monkeypatch.setattr(companion, "catalog", old)
        with pytest.raises(ValueError, match="canary_capability_required"):
            await worker.run(selected)
        assert state.fetches == 0
    elif kind == "disable_after_reset":
        state.disable = True
        with pytest.raises(ValueError, match="plan_disabled"):
            await worker.run(selected)
    else:
        state.interrupt = True
        with pytest.raises(RuntimeError, match="synthetic crash"):
            await worker.run(selected)
        with pytest.raises(ValueError, match="interrupted_requires_attention"):
            await worker.run(selected)
        assert state.resets == 1
        other = selected.model_copy(update={"evaluation_id": uuid4()})
        (worker.directory / "canary-plan.json").write_text(other.model_dump_json())
        with pytest.raises(ValueError, match="already_bound"):
            await worker.run(other)
    assert companion.start_calls == 0
