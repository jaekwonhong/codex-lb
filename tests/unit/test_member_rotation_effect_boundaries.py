"""Actual worker/controller/reset integration with isolated durable state and fake effects."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import MemberRotationQuotaOperation, WorkspaceMemberFinalUsageSnapshot
from app.modules.member_rotation_operator import adapter as operator_adapter
from app.modules.member_rotation_operator.repository import MemberRotationOperatorRepository
from app.modules.member_switch.rotation_controller import RotationController, rotation_controller_id
from app.modules.member_switch.rotation_plan import SCHEDULE_BINDING_ID
from app.modules.member_switch.rotation_worker import RotationWorker
from app.modules.member_switch.schemas import RotationControllerState
from app.modules.member_switch.service import MemberSwitchService
from app.modules.rate_limit_reset_credits import api as reset_api
from app.modules.rate_limit_reset_credits.rotation_resolution import resolve_rotation_reset_credit
from app.modules.rate_limit_reset_credits.store import RateLimitResetCreditsStore
from tests.unit.test_member_rotation_controller import rotation_context as rotation_context
from tests.unit.test_member_rotation_scheduler import worker_context as worker_context
from tests.unit.test_rotation_reset_credit_resolution import (
    StubEncryptor,
    _consume_response,
    _credit,
    _credits_response,
    _no_sleep,
)
from tests.unit.test_rotation_reset_credit_resolution import (
    fake_coordination_session as fake_coordination_session,
)
from tests.unit.test_rotation_reset_credit_resolution import fake_redeem_ledger as fake_redeem_ledger

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.mark.parametrize("boundary", ["controller_created", "snapshot_saved", "snapshot_published", "preview_created"])
async def test_worker_prestart_interruption_requires_attention_without_replay(worker_context, monkeypatch, boundary):
    worker, selected, counts, companion, controls, sessions = worker_context
    original_create = RotationController._create_or_load
    original_persist = RotationController._persist

    async def crash(*args, **kwargs):
        raise RuntimeError("synthetic_prestart_interruption")

    async def after_controller_create(self, state):
        await original_create(self, state)
        await crash()

    async def before_snapshot_publication(self, record, state):
        if state.snapshot_committed:
            await crash()
        return await original_persist(self, record, state)

    target, method, replacement = {
        "controller_created": (RotationController, "_create_or_load", after_controller_create),
        "snapshot_saved": (RotationController, "_persist", before_snapshot_publication),
        "snapshot_published": (MemberSwitchService, "create_rotation_run", crash),
        "preview_created": (RotationController, "_start_child", crash),
    }[boundary]
    with patch.object(target, method, replacement), pytest.raises(RuntimeError, match="synthetic_prestart"):
        await worker.run(selected)

    async def snapshots():
        async with sessions() as session:
            rows = (await session.scalars(select(WorkspaceMemberFinalUsageSnapshot))).all()
            return sorted((row.id, row.fetch_provenance, row.used_percent, row.observed_at) for row in rows)

    before_snapshots = await snapshots()
    before_binding = await controls.get(SCHEDULE_BINDING_ID)
    assert before_binding is not None
    before_fetches = counts.fetches
    restarted = RotationWorker(
        worker.directory, sessions=sessions, services=worker.services, runtime=worker.runtime, clock=worker.clock
    )
    for _ in range(3):
        await restarted.run(selected)
    async with worker.services(worker.runtime, lambda: worker.require_plan(selected)) as services:
        state = await services.controller.get(rotation_controller_id(str(selected.evaluation_id)))
    assert state is not None
    assert state.phase == "needs_attention"
    assert state.last_code == "rotation_prestart_interrupted_requires_attention"
    assert state.remove_state == state.invite_state == "not_attempted"
    assert counts.fetches == before_fetches and counts.resets == 1 and companion.start_calls == 0
    assert await snapshots() == before_snapshots
    after_binding = await controls.get(SCHEDULE_BINDING_ID)
    assert after_binding is not None and after_binding.payload == before_binding.payload
    async with sessions() as session:
        quota = (await session.scalars(select(MemberRotationQuotaOperation))).one()
        assert quota.reservation_released_at is None
        assert quota.remove_requested_at is None and quota.invite_requested_at is None
    monkeypatch.setattr(operator_adapter, "SessionLocal", sessions)
    projection = await operator_adapter.DurableRotationOperatorSnapshotAdapter().snapshot(
        workspace_id=selected.workspace_id, workspace_account_id=selected.workspace_account_id
    )
    assert projection is not None and projection.controller_status == "needs_attention"
    assert "rotation_prestart_interrupted_requires_attention" in projection.blocker_codes


@pytest.mark.parametrize("boundary", ["fetch", "pin"])
@pytest.mark.parametrize(
    "change",
    [
        "remove_plan",
        "expire_plan",
        "disable_intent",
        "stale_weekly",
        "runtime_invalid",
        "member_changed",
        "stale_membership_on_intent",
        "credential_changed",
    ],
)
async def test_worker_revalidates_after_reset_discovery_and_pin(
    worker_context, monkeypatch, fake_redeem_ledger, fake_coordination_session, boundary, change
):
    worker, selected, counts, companion, controls, sessions = worker_context
    consumed: list[str] = []
    changed = False
    original_observe_membership = companion.observe_membership
    original_pin = reset_api.pin_redeem_request
    original_runtime = worker.runtime.require
    original_intent = MemberRotationOperatorRepository.intent
    redeem_accounts = []

    async def intent(self, **kwargs):
        value = await original_intent(self, **kwargs)
        if changed and change == "stale_membership_on_intent":
            worker.clock.current += timedelta(seconds=31)
        return value

    async def observe_membership(workspace_id):
        current = (await original_observe_membership(workspace_id)).model_copy(update={"observed_at": worker.clock()})
        if changed and change == "member_changed":
            return current.model_copy(
                update={"members": [member for member in current.members if member.classification == "owner"]}
            )
        return current

    def runtime(expected):
        if changed and change == "runtime_invalid":
            raise ValueError("rotation_runtime_attestation_invalid")
        return original_runtime(expected)

    async def revoke():
        nonlocal changed
        changed = True
        if change == "remove_plan":
            (worker.directory / "canary-plan.json").unlink()
        elif change == "expire_plan":
            worker.clock.current = selected.expires_at
        elif change == "stale_weekly":
            worker.clock.current += timedelta(seconds=180)
        elif change == "disable_intent":
            async with sessions() as session:
                await MemberRotationOperatorRepository(session).set_intent(
                    workspace_id=selected.workspace_id,
                    workspace_account_id=selected.workspace_account_id,
                    enabled=False,
                    expected_version=1,
                )
        elif change == "credential_changed":
            redeem_accounts[0].chatgpt_user_id = "different-credential-principal"

    async def fetch_credits(*args, **kwargs):
        if boundary == "fetch":
            await revoke()
        return _credits_response([_credit("synthetic-credit", expires_at="2099-01-01T00:00:00Z")])

    async def pin(account_id, request_id, credit_id):
        value = await original_pin(account_id, request_id, credit_id)
        if boundary == "pin":
            await revoke()
        return value

    async def consume(*args, **kwargs):
        consumed.append("consume")
        return _consume_response("synthetic-credit")

    async def resolver(account, **kwargs):
        redeem_accounts.append(account)
        return await resolve_rotation_reset_credit(
            account,
            **kwargs,
            store=RateLimitResetCreditsStore(),
            encryptor=StubEncryptor(),
            fetch_fn=fetch_credits,
            consume_fn=consume,
            sleep_fn=_no_sleep,
        )

    monkeypatch.setattr(companion, "observe_membership", observe_membership)
    monkeypatch.setattr(worker.runtime, "require", runtime)
    monkeypatch.setattr(MemberRotationOperatorRepository, "intent", intent)
    monkeypatch.setattr(reset_api, "pin_redeem_request", pin)
    monkeypatch.setattr("app.modules.member_switch.rotation_worker.resolve_rotation_reset_credit", resolver)
    expected_reason = {
        "remove_plan": "rotation_plan_disabled_changed_or_expired",
        "expire_plan": "rotation_plan_disabled_changed_or_expired",
        "disable_intent": "rotation_workspace_disabled",
        "stale_weekly": "rotation_reset_weekly:stale",
        "runtime_invalid": "rotation_runtime_attestation_invalid",
        "member_changed": "rotation_current_member_changed",
        "stale_membership_on_intent": "rotation_reset_membership_observation_expired",
        "credential_changed": "rotation_reset_account_identity_changed",
    }[change]
    with pytest.raises(ValueError, match=expected_reason):
        await worker.run(selected)
    assert consumed == [] and companion.start_calls == 0
    assert len(fake_redeem_ledger) == 1
    assert await controls.get(SCHEDULE_BINDING_ID) is not None


async def test_real_reset_guard_allows_one_consume_and_recovery_stops_membership(
    worker_context, monkeypatch, fake_redeem_ledger, fake_coordination_session
):
    worker, selected, counts, companion, controls, _ = worker_context
    consumed: list[str] = []

    async def fetch_credits(*args, **kwargs):
        return _credits_response([_credit("synthetic-credit", expires_at="2099-01-01T00:00:00Z")])

    async def consume(*args, **kwargs):
        consumed.append("consume")
        counts.used = 20.0
        return _consume_response("synthetic-credit")

    async def resolver(account, **kwargs):
        return await resolve_rotation_reset_credit(
            account,
            **kwargs,
            store=RateLimitResetCreditsStore(),
            encryptor=StubEncryptor(),
            fetch_fn=fetch_credits,
            consume_fn=consume,
            sleep_fn=_no_sleep,
        )

    monkeypatch.setattr("app.modules.member_switch.rotation_worker.resolve_rotation_reset_credit", resolver)
    await worker.run(selected)
    await worker.run(selected)
    assert consumed == ["consume"] and companion.start_calls == 0
    assert len(fake_redeem_ledger) == 1 and await controls.get(SCHEDULE_BINDING_ID) is not None


async def test_attention_publication_does_not_hide_a_concurrent_durable_start_claim(worker_context):
    worker, selected, counts, companion, controls, _ = worker_context
    await worker.run(selected)
    controller_id = rotation_controller_id(str(selected.evaluation_id))
    record = await controls.get(controller_id)
    assert record is not None and companion.start_calls == 1
    state = RotationControllerState.model_validate_json(record.payload)
    # Simulate an attention write racing the child's durable start claim before
    # the parent publishes its accounting state. The actual child/receipt stays.
    await controls.save(
        record,
        state.model_copy(
            update={
                "phase": "needs_attention",
                "remove_state": "not_attempted",
                "last_code": "rotation_prestart_interrupted_requires_attention",
                "terminal_reason": "rotation_prestart_interrupted_requires_attention",
            }
        ).model_dump_json(),
        complete=True,
    )
    await worker.run(selected)
    record = await controls.get(controller_id)
    assert record is not None
    reconciled = RotationControllerState.model_validate_json(record.payload)
    assert reconciled.remove_state == "unknown"
    assert reconciled.terminal_reason != "rotation_prestart_interrupted_requires_attention"
    assert counts.resets == 1 and companion.start_calls == 1
