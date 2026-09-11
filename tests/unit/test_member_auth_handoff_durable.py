from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.member_auth_handoff.durable import DurableMemberAuthHandoffService, StoredHandoffReader
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from tests.unit.test_member_auth_handoff_service import FakeOauth, FakeRepository, prepare_request
from tests.unit.test_member_switch_control import context as context

pytestmark = pytest.mark.unit


async def parent_claim(controls, action, previous=None):
    record = previous or await controls.create(str(uuid4()), "run", "{}", own_scope=True)
    return (await controls.claim(record, str(uuid4()), action, action, expected_revision=record.revision))[0]


async def test_auth_snapshot_survives_service_reconstruction_and_get_is_pure(context):
    _, controls, _, _, sessions = context
    repo, oauth = FakeRepository([]), FakeOauth()
    parent = await parent_claim(controls, "prepare_auth")
    service = DurableMemberAuthHandoffService(repo, oauth, controls=controls)
    prepared = await service.prepare(prepare_request(), managed_run_id=parent.id)
    assert prepared.pending_action is None
    assert prepared.last_command_id == parent.command_id
    before = len(oauth.requests)
    reader = StoredHandoffReader(MemberSwitchControlRepository(sessions))
    for _ in range(3):
        assert await reader.get_status(prepared.handoff_id) == prepared
    # Repeated prepare of the same command only returns its recorded result.
    rebuilt = DurableMemberAuthHandoffService(repo, oauth, controls=MemberSwitchControlRepository(sessions))
    assert await rebuilt.prepare(prepare_request(), managed_run_id=parent.id) == prepared
    assert len(oauth.requests) == before


async def test_auth_unknown_effect_survives_restart_without_another_oauth_request(context):
    _, controls, _, _, sessions = context
    repo, oauth = FakeRepository([]), FakeOauth()
    parent = await parent_claim(controls, "prepare_auth")

    class InterruptedOauth(FakeOauth):
        async def start_oauth(self, request):
            await super().start_oauth(request)
            raise KeyboardInterrupt("synthetic process termination")

    interrupted = InterruptedOauth()
    service = DurableMemberAuthHandoffService(repo, interrupted, controls=controls)
    with pytest.raises(KeyboardInterrupt):
        await service.prepare(prepare_request(), managed_run_id=parent.id)
    rebuilt = DurableMemberAuthHandoffService(repo, oauth, controls=MemberSwitchControlRepository(sessions))
    retained = await rebuilt.prepare(prepare_request(), managed_run_id=parent.id)
    assert retained.pending_action == "prepare_auth"
    reconciled = await rebuilt.reconcile_for_operation(
        prepare_request().member_switch_operation_id,
        managed_run_id=parent.id,
    )
    assert reconciled is not None and reconciled.pending_action == "prepare_auth"
    assert oauth.requests == []
    assert len(interrupted.requests) == 1
    assert (await controls.active()).id == parent.id


async def test_published_child_result_clears_pending_without_repeating_oauth(context, monkeypatch):
    _, controls, _, _, sessions = context
    repo, oauth = FakeRepository([]), FakeOauth()
    parent = await parent_claim(controls, "prepare_auth")
    original_save = controls.save

    async def lose_pending_clear(current, payload, **kwargs):
        if current.kind == "handoff" and current.pending_action == "prepare_auth" and kwargs.get("complete"):
            raise OSError("synthetic child pending-clear failure")
        return await original_save(current, payload, **kwargs)

    monkeypatch.setattr(controls, "save", lose_pending_clear)
    service = DurableMemberAuthHandoffService(repo, oauth, controls=controls)
    request = prepare_request()
    with pytest.raises(OSError, match="pending-clear"):
        await service.prepare(request, managed_run_id=parent.id)
    assert len(oauth.requests) == 1

    rebuilt = DurableMemberAuthHandoffService(
        repo,
        oauth,
        controls=MemberSwitchControlRepository(sessions),
    )
    recovered = await rebuilt.reconcile_for_operation(
        request.member_switch_operation_id,
        managed_run_id=parent.id,
    )
    assert recovered is not None
    assert recovered.state == "device_code_issued"
    assert recovered.pending_action is None
    assert len(oauth.requests) == 1


async def test_legacy_auth_mutations_cannot_bypass_parent_admission(context):
    _, controls, _, _, _ = context
    oauth = FakeOauth()
    service = DurableMemberAuthHandoffService(FakeRepository([]), oauth, controls=controls)
    with pytest.raises(ControlConflict, match="managed_run_command_required"):
        await service.prepare(prepare_request())
    with pytest.raises(ControlConflict, match="managed_run_command_required"):
        await service.advance("missing")
    assert oauth.requests == []


async def test_oauth_only_enrollment_parent_can_issue_device_code_without_old_auth(context):
    _, controls, _, _, _ = context
    repo, oauth = FakeRepository([]), FakeOauth()
    parent = await controls.create(str(uuid4()), "auth_enrollment", "{}", own_scope=True)
    parent = (
        await controls.claim(
            parent,
            str(uuid4()),
            "prepare_auth",
            "oauth-enrollment-prepare",
            expected_revision=parent.revision,
        )
    )[0]
    service = DurableMemberAuthHandoffService(repo, oauth, controls=controls)
    request = prepare_request().model_copy(
        update={
            "removed_email": None,
            "removed_user_id": None,
            "preserve_other_auth": True,
        }
    )

    prepared = await service.prepare(request, managed_run_id=parent.id)

    assert prepared.state == "device_code_issued"
    assert prepared.removed_email is None
    assert prepared.last_command_id == parent.command_id
    assert len(oauth.requests) == 1


async def test_advance_uses_a_new_parent_command_and_replays_only_stored_receipt(context):
    _, controls, _, _, sessions = context
    repo, oauth = FakeRepository([]), FakeOauth()
    parent = await parent_claim(controls, "prepare_auth")
    service = DurableMemberAuthHandoffService(repo, oauth, controls=controls)
    prepared = await service.prepare(prepare_request(), managed_run_id=parent.id)
    parent = await controls.save(parent, "{}", complete=True)
    parent = await parent_claim(controls, "advance_auth", parent)
    original_status = oauth.oauth_status
    oauth.oauth_status = AsyncMock(side_effect=original_status)
    result = await service.advance(prepared.handoff_id, managed_run_id=parent.id)
    rebuilt = DurableMemberAuthHandoffService(repo, oauth, controls=MemberSwitchControlRepository(sessions))
    assert await rebuilt.advance(prepared.handoff_id, managed_run_id=parent.id) == result
    assert result.state == "oauth_pending" and result.pending_action is None
    oauth.oauth_status.assert_awaited_once()


async def test_real_run_coordinator_and_durable_handoff_share_command_identity(context, monkeypatch):
    from app.modules.member_auth_handoff.catalog import MemberAuthHandoffCatalog, MemberAuthHandoffCatalogEntry
    from app.modules.member_switch.schemas import CreateRunRequest
    from app.modules.member_switch.service import MemberSwitchService
    from tests.unit.test_member_switch_control import WORKSPACE_ID, command

    _, controls, companion, _, sessions = context
    catalog = MemberAuthHandoffCatalog(
        entries=(
            MemberAuthHandoffCatalogEntry(
                preset_id="target",
                workspace_id="cdp-1",
                owner_email="owner@example.com",
                workspace_account_id=WORKSPACE_ID,
                email="target@example.com",
                user_id="user-Target",
            ),
        )
    )
    snapshot = (await companion.catalog()).model_copy(update={"catalog_fingerprint": catalog.fingerprint()})
    preview = (await companion.preview(None)).model_copy(update={"catalog_fingerprint": catalog.fingerprint()})
    monkeypatch.setattr(companion, "catalog", AsyncMock(return_value=snapshot))
    monkeypatch.setattr(companion, "preview", AsyncMock(return_value=preview))
    repo, oauth = FakeRepository([]), FakeOauth()
    oauth.oauth_status = AsyncMock(wraps=oauth.oauth_status)
    auth = DurableMemberAuthHandoffService(repo, oauth, controls=controls, catalog=catalog)
    service = MemberSwitchService(controls, companion, auth)
    run = await service.create(
        CreateRunRequest(
            run_id=uuid4(),
            workspace_id="cdp-1",
            preset_id="target",
            catalog_fingerprint=catalog.fingerprint(),
        )
    )
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth"):
        run = await command(service, run, action)
    assert run.phase == "auth_prepared" and run.auth_state == "device_code_issued"
    assert len(oauth.requests) == 1
    restored_controls = MemberSwitchControlRepository(sessions)
    rebuilt = MemberSwitchService(
        restored_controls,
        companion,
        DurableMemberAuthHandoffService(
            repo,
            oauth,
            controls=restored_controls,
            catalog=catalog,
        ),
    )
    assert await rebuilt.get(run.id) == run
    run = await command(rebuilt, run, "observe_auth")
    oauth.oauth_status.assert_not_called()
    run = await command(rebuilt, run, "advance_auth")
    assert run.auth_state == "oauth_pending" and run.pending_action is None
    oauth.oauth_status.assert_awaited_once()
