from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import MemberSwitchCommandReceipt, MemberSwitchControlRecord
from app.modules.member_switch.admission import local_admission
from app.modules.member_switch.repository import AdmissionSnapshot, ControlRecord, MemberSwitchControlRepository
from app.modules.workspace_member_controller.legacy_mutation_journal import LegacyMembershipMutationJournal
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationAdmissionEvidence,
    MembershipMutationCommand,
    MembershipMutationReceipt,
    MembershipMutationSpec,
    MembershipMutationState,
    MembershipSubject,
)
from app.modules.workspace_member_controller.mutation_service import (
    MembershipMutationError,
    WorkspaceMembershipMutationService,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
OPERATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
COMMAND_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def command() -> MembershipMutationCommand:
    return MembershipMutationCommand(
        operation_id=OPERATION_ID,
        command_id=COMMAND_ID,
        expected_revision=0,
        mutation=MembershipMutationSpec(
            action="switch",
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="c" * 64,
            incoming=MembershipSubject(preset_id="incoming", email="incoming@example.com", user_id="user-Incoming"),
            outgoing=MembershipSubject(preset_id="outgoing", email="outgoing@example.com", user_id="user-Outgoing"),
        ),
    )


def receipt(cmd: MembershipMutationCommand) -> MembershipMutationReceipt:
    return MembershipMutationReceipt(
        operation_id=str(cmd.operation_id),
        command_id=str(cmd.command_id),
        request_fingerprint=cmd.fingerprint(),
        action="switch",
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        outcome="completed",
        code="switch_completed",
        observed_at=NOW,
        remove_effect="confirmed",
        add_effect="confirmed",
        final_membership_confirmed=True,
    )


def unknown_receipt(cmd: MembershipMutationCommand) -> MembershipMutationReceipt:
    return MembershipMutationReceipt(
        operation_id=str(cmd.operation_id),
        command_id=str(cmd.command_id),
        request_fingerprint=cmd.fingerprint(),
        action="switch",
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        outcome="outcome_unknown",
        code="canary_effect_unresolved:acceptance_settlement_not_observed",
        observed_at=NOW,
        remove_effect="unknown",
        add_effect="unknown",
        final_membership_confirmed=False,
    )


class LostReplyEffects:
    def __init__(self):
        self.execute_calls = 0

    async def execute(self, _command):
        self.execute_calls += 1
        raise RuntimeError("reply lost")

    async def reconcile(self, **_kwargs):
        return None


class RecoveredEffects:
    def __init__(self, value):
        self.value = value
        self.execute_calls = 0
        self.reconcile_calls = 0

    async def execute(self, _command):
        self.execute_calls += 1
        raise AssertionError("recovery must not replay execute")

    async def reconcile(self, **_kwargs):
        self.reconcile_calls += 1
        return self.value


class Admission:
    async def validate(self, cmd):
        return MembershipMutationAdmissionEvidence(
            workspace_id=cmd.mutation.workspace_id,
            workspace_account_id=cmd.mutation.workspace_account_id,
            catalog_fingerprint=cmd.mutation.catalog_fingerprint,
            membership_observed_at=NOW,
        )


async def create_schema(engine):
    async with engine.begin() as conn:
        await conn.run_sync(MemberSwitchControlRecord.__table__.create)
        await conn.run_sync(MemberSwitchCommandReceipt.__table__.create)


async def test_legacy_adapter_restarts_from_durable_claim_and_reconciles_without_replay(tmp_path):
    database = tmp_path / "controller-journal.sqlite3"
    url = f"sqlite+aiosqlite:///{database}"
    cmd = command()

    first_engine = create_async_engine(url)
    await create_schema(first_engine)
    first_sessions = async_sessionmaker(first_engine, expire_on_commit=False)
    first_effects = LostReplyEffects()
    first_service = WorkspaceMembershipMutationService(
        LegacyMembershipMutationJournal(MemberSwitchControlRepository(first_sessions)),
        Admission(),
        first_effects,
        clock=lambda: NOW,
    )
    with pytest.raises(MembershipMutationError, match="mutation_outcome_unknown"):
        await first_service.submit(cmd)
    await first_engine.dispose()

    second_engine = create_async_engine(url)
    second_sessions = async_sessionmaker(second_engine, expire_on_commit=False)
    recovered = RecoveredEffects(receipt(cmd))
    second_service = WorkspaceMembershipMutationService(
        LegacyMembershipMutationJournal(MemberSwitchControlRepository(second_sessions)),
        Admission(),
        recovered,
        clock=lambda: NOW,
    )
    pending = await second_service.submit(cmd)
    assert pending.phase == "outcome_unknown"
    assert recovered.execute_calls == 0
    completed = await second_service.reconcile(str(OPERATION_ID))
    assert completed.phase == "completed"
    assert recovered.execute_calls == 0
    assert recovered.reconcile_calls == 1

    controls = MemberSwitchControlRepository(second_sessions)
    durable = await controls.get(str(OPERATION_ID))
    assert durable is not None
    assert durable.pending_action is None
    assert durable.active_scope is None
    assert await controls.command_recorded(str(OPERATION_ID), str(COMMAND_ID), cmd.fingerprint()) is True
    await second_engine.dispose()


async def test_legacy_member_switch_admission_treats_settled_controller_history_as_inert():
    cmd = command()
    state = MembershipMutationState(
        operation_id=str(OPERATION_ID),
        mutation=cmd.mutation,
        command_fingerprint=cmd.fingerprint(),
        phase="completed",
        last_code="switch_completed",
        created_at=NOW,
        updated_at=NOW,
        admission=MembershipMutationAdmissionEvidence(
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="c" * 64,
            membership_observed_at=NOW,
        ),
        receipt=receipt(cmd),
    )

    class Controls:
        def __init__(self, record):
            self.record = record

        async def admission_snapshot(self):
            return AdmissionSnapshot((self.record,), ())

    settled = ControlRecord(
        id=str(OPERATION_ID),
        kind="controller_membership_mutation",
        active_scope=None,
        revision=3,
        payload=state.model_dump_json(by_alias=True),
        pending_action=None,
        command_id=str(COMMAND_ID),
        command_hash=cmd.fingerprint(),
    )
    assert (await local_admission(Controls(settled))).can_create is True  # type: ignore[arg-type]

    pending = ControlRecord(
        id=settled.id,
        kind=settled.kind,
        active_scope="member-switch",
        revision=2,
        payload=state.model_copy(update={"phase": "effect_pending", "receipt": None}).model_dump_json(by_alias=True),
        pending_action="switch",
        command_id=settled.command_id,
        command_hash=settled.command_hash,
    )
    blocked = await local_admission(Controls(pending))  # type: ignore[arg-type]
    assert blocked.can_create is False
    assert blocked.blockers[0].code == "controller_mutation_retained"


async def test_partial_recovery_evidence_is_durable_and_releases_legacy_scope_only_after_completion(tmp_path):
    database = tmp_path / "controller-recovery.sqlite3"
    url = f"sqlite+aiosqlite:///{database}"
    engine = create_async_engine(url)
    await create_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cmd = command()
    effects = RecoveredEffects(unknown_receipt(cmd))

    async def execute(_command):
        effects.execute_calls += 1
        return effects.value

    effects.execute = execute  # type: ignore[method-assign]
    service = WorkspaceMembershipMutationService(
        LegacyMembershipMutationJournal(MemberSwitchControlRepository(sessions)),
        Admission(),
        effects,
        clock=lambda: NOW,
    )
    pending = await service.submit(cmd)
    assert pending.phase == "outcome_unknown"

    child = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    prepared = await service.prepare_partial_recovery(str(OPERATION_ID), recovery_client_flow_id=child)
    controls = MemberSwitchControlRepository(sessions)
    retained = await controls.get(str(OPERATION_ID))
    assert retained is not None
    assert retained.active_scope == "member-switch"
    assert retained.pending_action == "switch"
    assert prepared.schema_version == 2
    assert prepared.recovery is not None and prepared.recovery.phase == "prepared"

    recovered = await service.complete_partial_recovery(
        str(OPERATION_ID),
        recovery_client_flow_id=child,
        companion_operation_id="recovery-child",
        cleanup_confirmed=True,
        restoration_confirmed=True,
    )
    assert recovered.phase == "recovered"
    assert recovered.receipt is not None and recovered.receipt.outcome == "outcome_unknown"

    durable = await controls.get(str(OPERATION_ID))
    assert durable is not None
    assert durable.active_scope is None
    assert durable.pending_action is None
    reread = LegacyMembershipMutationJournal(controls)._convert(durable)
    assert reread.state.schema_version == 2
    assert reread.state.phase == "recovered"
    assert reread.state.recovery is not None
    assert reread.state.recovery.restoration_confirmed is True
    await engine.dispose()
