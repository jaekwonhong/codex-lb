from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Account, MemberSwitchCommandReceipt, MemberSwitchControlRecord
from app.modules.member_auth_handoff.schemas import MemberAuthHandoffResponse
from app.modules.member_switch.participants import participant_fingerprint
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.schemas import (
    BrowserReceipt,
    Catalog,
    CloseReceipt,
    CommandRequest,
    CompanionAdmission,
    CreateRunRequest,
    CurrentMember,
    FinalizeReceipt,
    Member,
    MembershipObservation,
    MembershipObservationMember,
    Operation,
    ParticipantReceipt,
    Preview,
    RecipientReceipt,
    StartReceipt,
    Workspace,
)
from app.modules.member_switch.service import MemberSwitchService

pytestmark = pytest.mark.unit
WORKSPACE_ID = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"


class FakeCompanion:
    def __init__(self):
        self.calls = []
        self.participant_receipts = {}
        self.lose_participant = False
        self.receipt = None
        self.lose_start = False
        self.wait_start = None
        self.started = asyncio.Event()
        self.release_pending = False
        self.catalog_user_id = "user-Target"
        self.snapshot = Operation(
            operation_id="operation-1",
            member_switch_operation_id="operation-1",
            workspace_id="cdp-1",
            workspace_account_id=WORKSPACE_ID,
            target_email="target@example.com",
            target_user_id="user-Target",
            stage="completed",
            code="member_added",
            removed_email=None,
            removed_user_id=None,
            membership_state="active",
            updated_at=datetime.now(timezone.utc),
        )

    async def admission(self):
        self.calls.append("admission")
        return CompanionAdmission(can_start=True, code="ready")

    async def catalog(self):
        self.calls.append("catalog")
        fingerprint = "b" * 64 if self.catalog_user_id == "user-TargetCorrected" else "a" * 64
        return Catalog(
            enabled=True,
            schema_version=1,
            catalog_fingerprint=fingerprint,
            capabilities=[
                "recipient_acceptance",
                "recipient_session_readiness",
                "post_add_device_auth",
                "ego_lite_member_browser_v1",
                "ego_lite_device_auth_automation_v1",
                "ego_lite_owner_membership_observation_v1",
                "ego_lite_owner_membership_mutation_v1",
                "ego_lite_recipient_membership_lifecycle_v1",
                "durable_client_flow",
                "durable_participant_commands_v1",
                "managed_member_switch_v1",
            ],
            workspaces=[
                Workspace(
                    id="cdp-1",
                    workspace_account_id=WORKSPACE_ID,
                    workspace_name="Synthetic",
                    owner_email="owner@example.com",
                    members=[
                        Member(
                            preset_id="target",
                            display_name="Target",
                            email="target@example.com",
                            user_id=self.catalog_user_id,
                        )
                    ],
                )
            ],
        )

    async def observe_membership(self, workspace_id):
        self.calls.append("observe_membership:" + workspace_id)
        self.catalog_user_id = "user-TargetCorrected"
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id="cdp-1",
            workspace_account_id=WORKSPACE_ID,
            catalog_fingerprint="a" * 64,
            observed_at=datetime.now(timezone.utc),
            complete=True,
            owner_verified=True,
            identity_ambiguous=False,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=[
                MembershipObservationMember(
                    email="current@example.com",
                    user_id="user-Current",
                    preset_id=None,
                    classification="unknown",
                )
            ],
        )

    async def preview(self, request):
        self.calls.append("preview")
        return Preview(
            ready=True,
            code="ready",
            preview_token="preview-1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            workspace_name="Synthetic",
            owner_email="owner@example.com",
            target_email="target@example.com",
            remove_email=None,
            catalog_fingerprint="a" * 64,
        )

    async def start(self, request):
        self.calls.append("start")
        self.receipt = StartReceipt(accepted=True, code="accepted", operation_id="operation-1")
        self.started.set()
        if self.wait_start:
            await self.wait_start.wait()
        if self.lose_start:
            raise ControlConflict("companion_outcome_unknown")
        return self.receipt

    async def lookup(self, client_flow_id):
        self.calls.append("lookup")
        if self.release_pending:
            return StartReceipt(accepted=True, code="operation_release_pending", operation_id="operation-1")
        return self.receipt

    async def operation(self, operation_id):
        self.calls.append("operation")
        return self.snapshot

    async def prepare_session(self, request):
        self.calls.append("prepare_session")
        return RecipientReceipt(ready=True, code="ready", target_email="target@example.com", outcome_unknown=False)

    async def open_browser(self, request):
        self.calls.append("open_browser")
        return BrowserReceipt(
            accepted=True,
            code="opened",
            browser_operation_id="browser-1",
            target_email="target@example.com",
            outcome_unknown=False,
        )

    async def close_browser(self, browser_id):
        self.calls.append("close_browser")
        return CloseReceipt(closed=True, code="closed", outcome_unknown=False)

    async def participant(self, request):
        if request.command_id in self.participant_receipts:
            return self.participant_receipts[request.command_id]
        result = (
            await self.prepare_session(request)
            if request.action == "prepare_session"
            else await self.open_browser(request)
            if request.action == "open_browser"
            else await self.close_browser(request.browser_operation_id)
        )
        key = {"prepare_session": "session", "open_browser": "browser", "close_browser": "close"}[request.action]
        receipt = ParticipantReceipt(
            schema_version=1,
            command_id=request.command_id,
            client_flow_id=request.client_flow_id,
            action=request.action,
            member_switch_operation_id=request.member_switch_operation_id,
            identity=request.identity,
            request_hash=participant_fingerprint(request),
            state="completed",
            code=result.code,
            recorded_at=datetime.now(timezone.utc),
            browser_operation_id=request.browser_operation_id,
            **{key: result},
        )
        self.participant_receipts[request.command_id] = receipt
        if self.lose_participant:
            raise ControlConflict("synthetic_response_lost")
        return receipt

    async def participant_receipt(self, command_id):
        self.calls.append("participant_receipt")
        return self.participant_receipts.get(command_id)

    async def reconcile_participant_receipt(self, command_id):
        self.calls.append("reconcile_participant_receipt")
        return self.participant_receipts.get(command_id)

    async def finalize(self, operation_id):
        self.calls.append("finalize")
        return FinalizeReceipt(released=True, code="released")


class FakeAuth:
    def __init__(self, controls):
        self.calls = []
        self.controls = controls
        self.device_busy = False
        self.snapshot = MemberAuthHandoffResponse(
            handoff_id="auth-1",
            member_switch_operation_id="operation-1",
            preset_id="target",
            workspace_account_id=WORKSPACE_ID,
            target_email="target@example.com",
            target_user_id="user-Target",
            state="device_code_issued",
            flow_id="oauth-1",
            verification_url="https://example.invalid/device",
            user_code="TEST-CODE",
            expires_in_seconds=600,
            error_code=None,
            error_message=None,
        )

    def bind_catalog(self, catalog):
        pass

    def validate_identity(self, identity, removed_email=None):
        if identity.catalog_fingerprint != "a" * 64:
            raise ControlConflict("auth_catalog_identity_mismatch")

    async def prepare(self, request, *, managed_run_id=None):
        self.calls.append("prepare")
        parent = await self.controls.get(managed_run_id)
        self.snapshot = self.snapshot.model_copy(update={"last_command_id": parent.command_id})
        return self.snapshot

    async def advance(self, handoff_id, *, managed_run_id=None):
        self.calls.append("advance")
        parent = await self.controls.get(managed_run_id)
        self.snapshot = self.snapshot.model_copy(update={"state": "completed", "last_command_id": parent.command_id})
        return self.snapshot

    async def get_status(self, handoff_id):
        self.calls.append("get")
        return self.snapshot

    async def get_for_operation(self, operation_id):
        self.calls.append("lookup")
        return self.snapshot

    async def ensure_device_oauth_available(self, expected_flow_id=None):
        if self.device_busy:
            raise ControlConflict("device_oauth_busy")

    async def reconcile_for_operation(self, operation_id, *, managed_run_id=None):
        self.calls.append("reconcile_lookup")
        return self.snapshot


@pytest_asyncio.fixture
async def context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'control.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Account.__table__.create)
        await connection.run_sync(MemberSwitchControlRecord.__table__.create)
        await connection.run_sync(MemberSwitchCommandReceipt.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = FakeCompanion()
    auth = FakeAuth(controls)
    service = MemberSwitchService(controls, companion, auth)
    yield service, controls, companion, auth, sessions
    await engine.dispose()


async def create_run(service):
    return await service.create(
        CreateRunRequest(run_id=uuid4(), workspace_id="cdp-1", preset_id="target", catalog_fingerprint="a" * 64)
    )


async def command(service, run, action):
    return await service.command(
        run.id, CommandRequest(command_id=uuid4(), expected_revision=run.revision, action=action)
    )


async def test_manual_path_and_get_do_not_advance(context):
    service, controls, companion, auth, _ = context
    run = await create_run(service)
    assert run.allowed_actions == ["start", "cancel"]
    before = list(companion.calls)
    assert (await service.get(run.id)).phase == "previewed"
    assert (await service.active()).id == run.id
    assert companion.calls == before and not auth.calls
    run = await command(service, run, "start")
    assert run.phase == "membership_requested"
    run = await command(service, run, "observe_membership")
    assert run.phase == "membership_confirmed"
    assert "finish" not in run.allowed_actions
    run = await command(service, run, "prepare_session")
    assert run.phase == "session_prepared" and auth.calls == []
    run = await command(service, run, "prepare_auth")
    assert run.phase == "auth_prepared"
    assert auth.calls == ["prepare"]
    run = await command(service, run, "open_browser")
    assert run.phase == "auth_browser_opened"
    run = await command(service, run, "observe_auth")
    assert run.phase == "auth_browser_opened" and "advance" not in auth.calls
    run = await command(service, run, "advance_auth")
    assert run.phase == "auth_confirmed" and "finish" not in run.allowed_actions
    run = await command(service, run, "close_browser")
    run = await command(service, run, "finish")
    assert run.phase == "completed" and run.allowed_actions == []
    assert await controls.active() is None


def pre_membership_failure_operation(*, with_invitation: bool = False, with_mutation_stage: bool = False) -> Operation:
    trace = [
        {
            "sequence": 1,
            "stage": "queued",
            "code": "queued",
            "at": datetime.now(timezone.utc),
        },
        {
            "sequence": 2,
            "stage": "confirming_personal",
            "code": "confirming_owner_personal_before_membership_change",
            "at": datetime.now(timezone.utc),
        },
    ]
    if with_mutation_stage:
        trace.append(
            {
                "sequence": 3,
                "stage": "removing",
                "code": "removing",
                "at": datetime.now(timezone.utc),
            }
        )
    trace.append(
        {
            "sequence": len(trace) + 1,
            "stage": "failed",
            "code": "personal_switch_not_confirmed",
            "at": datetime.now(timezone.utc),
        }
    )
    return Operation.model_validate(
        {
            "operationId": "operation-1",
            "memberSwitchOperationId": "operation-1",
            "workspaceId": "cdp-1",
            "workspaceAccountId": WORKSPACE_ID,
            "targetEmail": "target@example.com",
            "targetUserId": "user-Target",
            "stage": "failed",
            "code": "personal_switch_not_confirmed",
            "removedEmail": "current@example.com",
            "removedUserId": "user-Current",
            "membershipState": "unknown",
            "updatedAt": datetime.now(timezone.utc),
            "trace": trace,
            "invitationSettlement": {
                "invitationIssued": True,
                "automaticObservationAttempts": 1,
                "automaticSettlementConfirmed": False,
                "pendingInvitationId": "invite-1",
                "fallbackUsed": False,
                "finalMembershipConfirmed": False,
                "invitationAttempted": True,
                "recipientWorkspaceRefreshAttempts": 1,
                "recipientWorkspaceObserved": False,
            }
            if with_invitation
            else None,
        }
    )


async def test_definitive_pre_membership_failure_can_be_explicitly_finalized(context):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    run = await command(service, run, "start")
    companion.snapshot = pre_membership_failure_operation()

    run = await command(service, run, "observe_membership")

    assert run.phase == "needs_attention"
    assert run.last_code == "personal_switch_not_confirmed"
    assert "finish" in run.allowed_actions
    run = await command(service, run, "finish")
    assert run.phase == "completed"
    assert run.last_code == "run_finalized"
    assert await controls.active() is None
    assert "finalize" in companion.calls


@pytest.mark.parametrize("unsafe_kind", ("invitation", "mutation_stage"))
async def test_failed_operation_with_membership_effect_evidence_cannot_be_finalized(context, unsafe_kind):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    run = await command(service, run, "start")
    companion.snapshot = pre_membership_failure_operation(
        with_invitation=unsafe_kind == "invitation",
        with_mutation_stage=unsafe_kind == "mutation_stage",
    )

    run = await command(service, run, "observe_membership")

    assert run.phase == "needs_attention"
    assert "finish" not in run.allowed_actions
    before = await controls.get(run.id)
    with pytest.raises(ControlConflict, match="transition_not_allowed"):
        await command(service, run, "finish")
    assert await controls.get(run.id) == before
    assert "finalize" not in companion.calls


async def test_existing_device_oauth_blocks_member_switch_auth_before_claim(context):
    service, controls, _, auth, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session"):
        run = await command(service, run, action)
    before = await controls.get(run.id)
    assert before is not None and before.pending_action is None
    auth.device_busy = True

    with pytest.raises(ControlConflict, match="device_oauth_busy"):
        await command(service, run, "prepare_auth")

    after = await controls.get(run.id)
    assert after == before
    assert auth.calls == []


async def test_new_run_requires_owner_ego_observation_capability_before_persisting(context):
    service, controls, companion, _, _ = context
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item
                    for item in catalog.capabilities
                    if item != "ego_lite_owner_membership_observation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await create_run(service)

    assert await controls.active() is None
    assert all(not call.startswith("observe_membership:") for call in companion.calls)


async def test_new_run_requires_owner_ego_mutation_capability_before_persisting(context):
    service, controls, companion, _, _ = context
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item
                    for item in catalog.capabilities
                    if item != "ego_lite_owner_membership_mutation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await create_run(service)

    assert await controls.active() is None
    assert "start" not in companion.calls


async def test_start_rechecks_owner_ego_mutation_capability_before_claiming_intent(context):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    before = await controls.get(run.id)
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item
                    for item in catalog.capabilities
                    if item != "ego_lite_owner_membership_mutation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="catalog_identity_mismatch"):
        await command(service, run, "start")

    assert await controls.get(run.id) == before
    assert "start" not in companion.calls


async def test_new_run_requires_device_auth_automation_capability_before_persisting(context):
    service, controls, companion, _, _ = context
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item for item in catalog.capabilities if item != "ego_lite_device_auth_automation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await create_run(service)

    assert await controls.active() is None
    assert "start" not in companion.calls


async def test_prepare_auth_rechecks_device_auth_automation_before_claiming_intent(context):
    service, controls, companion, auth, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session"):
        run = await command(service, run, action)
    before = await controls.get(run.id)
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item for item in catalog.capabilities if item != "ego_lite_device_auth_automation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await command(service, run, "prepare_auth")

    assert await controls.get(run.id) == before
    assert auth.calls == []


async def test_open_browser_rechecks_device_auth_automation_capability_before_participant_effect(context):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth"):
        run = await command(service, run, action)
    before = await controls.get(run.id)
    browser_calls = companion.calls.count("open_browser")
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item for item in catalog.capabilities if item != "ego_lite_device_auth_automation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await command(service, run, "open_browser")

    assert await controls.get(run.id) == before
    assert companion.calls.count("open_browser") == browser_calls


async def test_new_run_requires_recipient_ego_lifecycle_capability_before_persisting(context):
    service, controls, companion, _, _ = context
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item
                    for item in catalog.capabilities
                    if item != "ego_lite_recipient_membership_lifecycle_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await create_run(service)

    assert await controls.active() is None
    assert "start" not in companion.calls


async def test_start_rechecks_recipient_ego_lifecycle_capability_before_claiming_intent(context):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    before = await controls.get(run.id)
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item
                    for item in catalog.capabilities
                    if item != "ego_lite_recipient_membership_lifecycle_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="catalog_identity_mismatch"):
        await command(service, run, "start")

    assert await controls.get(run.id) == before
    assert "start" not in companion.calls


async def test_catalog_refresh_requires_owner_ego_observation_capability_before_observe(context):
    service, _, companion, _, _ = context
    original_catalog = companion.catalog

    async def old_catalog():
        catalog = await original_catalog()
        return catalog.model_copy(
            update={
                "capabilities": [
                    item
                    for item in catalog.capabilities
                    if item != "ego_lite_owner_membership_observation_v1"
                ]
            }
        )

    companion.catalog = old_catalog

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await service.refresh_catalog()

    assert "observe_membership:cdp-1" not in companion.calls


async def test_catalog_refresh_observes_current_member_and_returns_post_correction_identity(context):
    service, _, companion, _, _ = context

    catalog = await service.refresh_catalog()

    workspace = catalog.workspaces[0]
    assert workspace.current_members == [
        CurrentMember(email="current@example.com", user_id="user-Current", auth_state="unmanaged")
    ]
    assert workspace.membership_code == "ok"
    assert workspace.membership_observed_at is not None
    assert workspace.members[0].user_id == "user-TargetCorrected"
    assert catalog.catalog_fingerprint == "b" * 64
    assert companion.calls == ["admission", "catalog", "observe_membership:cdp-1", "catalog"]


async def test_catalog_refresh_is_blocked_before_live_observation_when_run_is_active(context):
    service, _, companion, _, _ = context
    await create_run(service)
    before = list(companion.calls)

    with pytest.raises(ControlConflict, match="member_switch_catalog_refresh_requires_idle"):
        await service.refresh_catalog()

    assert companion.calls == before


async def test_lost_start_reply_recovered_from_receipt_not_replayed(context):
    service, controls, companion, auth, sessions = context
    run = await create_run(service)
    companion.lose_start = True
    with pytest.raises(ControlConflict, match="outcome_unknown"):
        await command(service, run, "start")
    reconstructed = MemberSwitchService(MemberSwitchControlRepository(sessions), companion, auth)
    run = await reconstructed.get(run.id)
    assert run.phase == "outcome_unknown"
    with pytest.raises(ControlConflict):
        await create_run(reconstructed)
    recovered = await command(reconstructed, run, "reconcile")
    assert recovered.phase == "membership_confirmed"
    assert companion.calls.count("start") == 1


async def test_duplicate_command_and_identity_conflict(context):
    service, _, companion, _, _ = context
    run = await create_run(service)
    request = CommandRequest(command_id=uuid4(), expected_revision=run.revision, action="start")
    first = await service.command(run.id, request)
    assert await service.command(run.id, request) == first
    with pytest.raises(ControlConflict, match="command_identity_mismatch"):
        await service.command(run.id, request.model_copy(update={"action": "finish"}))
    assert companion.calls.count("start") == 1
    newer = await command(service, first, "observe_membership")
    assert (await service.command(run.id, request)).revision == newer.revision
    with pytest.raises(ControlConflict, match="command_identity_mismatch"):
        await service.command(run.id, request.model_copy(update={"expected_revision": newer.revision}))
    assert companion.calls.count("start") == 1


async def test_two_instances_admit_only_one_external_command(context):
    service, _, companion, auth, sessions = context
    run = await create_run(service)
    companion.wait_start = asyncio.Event()
    first = asyncio.create_task(command(service, run, "start"))
    await companion.started.wait()
    other = MemberSwitchService(MemberSwitchControlRepository(sessions), companion, auth)
    with pytest.raises(ControlConflict):
        await command(other, run, "start")
    companion.wait_start.set()
    await first
    assert companion.calls.count("start") == 1


async def test_unknown_receipt_and_mismatched_receipt_never_release(context):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    companion.lose_start = True
    with pytest.raises(ControlConflict):
        await command(service, run, "start")
    run = await service.get(run.id)
    companion.receipt = None
    with pytest.raises(ControlConflict, match="still_unknown"):
        await command(service, run, "reconcile")
    companion.receipt = StartReceipt(accepted=True, code="accepted", operation_id="another-operation")
    with pytest.raises(ControlConflict, match="identity_mismatch"):
        await command(service, run, "reconcile")
    assert (await controls.active()).id == run.id
    assert companion.calls.count("start") == 1


async def test_db_failure_after_external_start_keeps_intent(context, monkeypatch):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    original = controls.save

    async def fail_save(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(controls, "save", fail_save)
    with pytest.raises(OSError):
        await command(service, run, "start")
    monkeypatch.setattr(controls, "save", original)
    run = await service.get(run.id)
    assert run.phase == "outcome_unknown"
    assert (await command(service, run, "reconcile")).phase == "membership_confirmed"
    assert companion.calls.count("start") == 1


async def test_cancel_only_before_external_mutation(context):
    service, _, companion, _, _ = context
    run = await create_run(service)
    run = await command(service, run, "cancel")
    assert run.phase == "completed" and "start" not in companion.calls
    run = await create_run(service)
    run = await command(service, run, "start")
    with pytest.raises(ControlConflict, match="transition_not_allowed"):
        await command(service, run, "cancel")


async def test_server_auth_catalog_is_checked_before_membership_mutation(context, monkeypatch):
    service, _, companion, auth, _ = context
    run = await create_run(service)

    def mismatch(*args):
        raise ControlConflict("auth_catalog_identity_mismatch")

    monkeypatch.setattr(auth, "validate_identity", mismatch)
    with pytest.raises(ControlConflict, match="auth_catalog_identity_mismatch"):
        await command(service, run, "start")
    assert "start" not in companion.calls
    assert (await service.get(run.id)).pending_action is None


async def test_finish_response_loss_uses_finalization_receipt_without_repeat(context, monkeypatch):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth", "advance_auth"):
        run = await command(service, run, action)
    save = controls.save

    async def unavailable(*args, **kwargs):
        raise OSError("parent receipt commit unavailable")

    monkeypatch.setattr(controls, "save", unavailable)
    with pytest.raises(OSError):
        await command(service, run, "finish")
    monkeypatch.setattr(controls, "save", save)
    run = await service.get(run.id)
    assert run.pending_action == "finish"
    with pytest.raises(ControlConflict, match="finalization_outcome_still_unknown"):
        await command(service, run, "reconcile")
    companion.receipt = StartReceipt(accepted=True, code="operation_finalized", operation_id="operation-1")
    recovered = await command(service, run, "reconcile")
    assert recovered.phase == "completed"
    assert companion.calls.count("finalize") == 1
    assert await controls.active() is None


async def test_reconcile_completes_exact_persisted_release_intent_once(context, monkeypatch):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth", "advance_auth"):
        run = await command(service, run, action)
    save = controls.save

    async def fail_after_release(*args, **kwargs):
        companion.release_pending = True
        raise OSError("synthetic crash after durable release marker")

    monkeypatch.setattr(controls, "save", fail_after_release)
    with pytest.raises(OSError):
        await command(service, run, "finish")
    monkeypatch.setattr(controls, "save", save)
    retained = await service.get(run.id)
    assert retained.pending_action == "finish"
    before = companion.calls.count("finalize")
    recovered = await command(service, retained, "reconcile")
    assert recovered.phase == "completed"
    assert companion.calls.count("finalize") == before + 1
    assert await controls.active() is None


async def test_pending_close_reconciles_without_replaying_browser_command(context, monkeypatch):
    service, controls, companion, auth, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth", "open_browser"):
        run = await command(service, run, action)
    companion.lose_participant = True
    with pytest.raises(ControlConflict, match="synthetic_response_lost"):
        await command(service, run, "close_browser")
    retained = await controls.get(run.id)
    completed = companion.participant_receipts[retained.command_id]
    pending = completed.model_copy(update={"state": "pending", "close": None, "code": "participant_outcome_unknown"})
    companion.participant_receipts[retained.command_id] = pending
    run = await service.get(run.id)
    before = list(companion.calls)
    await service.get(run.id)
    assert companion.calls == before
    with pytest.raises(ControlConflict, match="participant_outcome_still_unknown"):
        await command(service, run, "reconcile")
    assert (await service.get(run.id)).allowed_actions == ["reconcile"]
    companion.participant_receipts[retained.command_id] = completed
    recovered = await command(service, run, "reconcile")
    assert recovered.phase == "needs_attention"
    assert recovered.pending_action is None
    assert recovered.browser_operation_id is None
    assert "prepare_session" in recovered.allowed_actions
    assert "open_browser" not in recovered.allowed_actions
    assert companion.calls.count("reconcile_participant_receipt") == 2
    assert companion.calls.count("close_browser") == 1
    assert companion.calls.count("open_browser") == 1
    assert auth.calls.count("prepare") == 1


@pytest.mark.parametrize("known_open_failure", [False, True])
async def test_explicit_session_recheck_reuses_existing_handoff(context, monkeypatch, known_open_failure):
    service, controls, companion, auth, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth"):
        run = await command(service, run, action)
    if known_open_failure:

        async def not_prepared(request):
            return BrowserReceipt(
                accepted=False,
                code="ego_member_session_not_prepared",
                browser_operation_id=None,
                target_email="target@example.com",
                outcome_unknown=False,
            )

        monkeypatch.setattr(companion, "open_browser", not_prepared)
        run = await command(service, run, "open_browser")
        assert run.last_code == "ego_member_session_not_prepared"
        assert run.phase == "needs_attention"
    else:
        run = await command(service, run, "open_browser")
        run = await command(service, run, "close_browser")
    assert run.phase == "needs_attention"
    assert "prepare_session" in run.allowed_actions
    assert "open_browser" not in run.allowed_actions
    old_handoff = run.handoff_id
    run = await command(service, run, "prepare_session")
    assert run.phase == "auth_prepared" and run.handoff_id == old_handoff
    assert "prepare_auth" not in run.allowed_actions
    assert "open_browser" in run.allowed_actions
    assert auth.calls.count("prepare") == 1
    assert companion.calls.count("start") == 1
    assert companion.calls.count("prepare_session") == 2


async def test_failed_same_handoff_session_recheck_does_not_reenable_browser_open(context, monkeypatch):
    service, _, companion, _, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth", "open_browser", "close_browser"):
        run = await command(service, run, action)
    assert "prepare_session" in run.allowed_actions
    assert "open_browser" not in run.allowed_actions
    original = companion.prepare_session

    async def login_required(request):
        companion.calls.append("prepare_session")
        return RecipientReceipt(
            ready=False,
            code="ego_profile_login_required",
            target_email="target@example.com",
            outcome_unknown=False,
        )

    monkeypatch.setattr(companion, "prepare_session", login_required)
    run = await command(service, run, "prepare_session")
    assert run.last_code == "ego_profile_login_required"
    assert run.phase == "needs_attention"
    assert "prepare_session" in run.allowed_actions
    assert "open_browser" not in run.allowed_actions
    run = await command(service, run, "observe_auth")
    assert run.phase == "needs_attention" and "open_browser" not in run.allowed_actions
    monkeypatch.setattr(companion, "prepare_session", original)
    run = await command(service, run, "prepare_session")
    assert "open_browser" in run.allowed_actions


async def test_session_recheck_stays_blocked_for_live_target_or_terminal_auth(context):
    service, _, _, _, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth", "open_browser"):
        run = await command(service, run, action)
    assert "prepare_session" not in run.allowed_actions
    with pytest.raises(ControlConflict, match="transition_not_allowed"):
        await command(service, run, "prepare_session")
    run = await command(service, run, "advance_auth")
    run = await command(service, run, "close_browser")
    assert "prepare_session" not in run.allowed_actions


@pytest.mark.parametrize("code", (
    "ego_owner_profile_login_required", "ego_owner_identity_mismatch", "ego_owner_identity_unavailable",
))
async def test_known_owner_preflight_failure_has_explicit_nonreplaying_closeout(context, code):
    service, controls, companion, auth, _ = context
    run = await create_run(service)
    run = await command(service, run, "start")
    failed = pre_membership_failure_operation()
    trace = list(failed.trace[:2])
    trace.append(failed.trace[-1].model_copy(update={"sequence": 3, "stage": "confirming_personal", "code": code}))
    trace.append(failed.trace[-1].model_copy(update={"sequence": 4, "code": code}))
    companion.snapshot = failed.model_copy(update={"code": code, "trace": trace})
    run = await command(service, run, "observe_membership")
    assert run.phase == "needs_attention"
    assert "finish" in run.allowed_actions
    before = list(companion.calls)
    run = await command(service, run, "finish")
    assert run.phase == "completed"
    assert await controls.active() is None
    assert companion.calls[len(before):] == ["finalize"]
    assert auth.calls == []


@pytest.mark.parametrize("bad_evidence", (
    "unknown", "missing_start", "gap", "duplicate", "different_terminal", "mutation_stage", "mutation_status",
    "invitation", "recipient_stage", "missing_result",
))
async def test_owner_preflight_closeout_rejects_unproven_or_posteffect_trace(context, bad_evidence):
    service, controls, companion, _, _ = context
    run = await create_run(service)
    run = await command(service, run, "start")
    code = "ego_owner_profile_login_required"
    failed = pre_membership_failure_operation(with_invitation=bad_evidence == "invitation")
    trace = list(failed.trace[:2])
    trace.append(failed.trace[-1].model_copy(update={"sequence": 3, "stage": "confirming_personal", "code": code}))
    trace.append(failed.trace[-1].model_copy(update={"sequence": 4, "code": code}))
    if bad_evidence == "unknown":
        code = "ego_owner_personal_outcome_unknown"
        trace[2] = trace[2].model_copy(update={"code": code})
        trace[3] = trace[3].model_copy(update={"code": code})
    elif bad_evidence == "missing_start":
        trace = trace[1:]
    elif bad_evidence == "gap":
        trace[2] = trace[2].model_copy(update={"sequence": 8})
    elif bad_evidence == "duplicate":
        trace[2] = trace[2].model_copy(update={"sequence": 2})
    elif bad_evidence == "different_terminal":
        trace[3] = trace[3].model_copy(update={"code": "unexpected_error"})
    elif bad_evidence == "mutation_stage":
        trace[2] = trace[2].model_copy(update={"stage": "removing"})
    elif bad_evidence == "mutation_status":
        trace[2] = trace[2].model_copy(update={"action": "delete", "status": 503})
    elif bad_evidence == "recipient_stage":
        trace[1] = trace[1].model_copy(update={"code": "confirming_outgoing_personal_before_removal"})
    elif bad_evidence == "missing_result":
        trace[2] = trace[2].model_copy(update={"code": "personal_confirmed"})
    companion.snapshot = failed.model_copy(update={"code": code, "trace": trace})
    run = await command(service, run, "observe_membership")
    assert "finish" not in run.allowed_actions
    before = await controls.get(run.id)
    with pytest.raises(ControlConflict, match="transition_not_allowed"):
        await command(service, run, "finish")
    assert await controls.get(run.id) == before
    assert "finalize" not in companion.calls
