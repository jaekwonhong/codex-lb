from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AccountStatus
from app.modules.member_auth_handoff.service import MemberAuthHandoffService, MemberAuthHandoffStore
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from tests.unit.test_member_auth_handoff_service import FakeOauth, FakeRepository, account, prepare_request
from tests.unit.test_member_switch_control import command, create_run
from tests.unit.test_member_switch_control import context as context

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("write_kind", ["claim", "save"])
async def test_cas_returns_its_own_committed_snapshot(context, write_kind):
    _, controls, _, _, sessions = context
    original = await controls.create(str(uuid4()), "run", "original", own_scope=True)
    interleaved = False

    class InterleavingSession(AsyncSession):
        async def commit(self):
            nonlocal interleaved
            await super().commit()
            if not interleaved:
                interleaved = True
                latest = await controls.get(original.id)
                await controls.save(latest, "second writer", complete=True)

    raced = MemberSwitchControlRepository(
        async_sessionmaker(sessions.kw["bind"], class_=InterleavingSession, expire_on_commit=False)
    )
    if write_kind == "claim":
        result, execute = await raced.claim(
            original, str(uuid4()), "start", "fingerprint", expected_revision=original.revision
        )
        assert execute
        assert result.pending_action == "start"
        assert result.payload == "original"
    else:
        result = await raced.save(original, "first writer", complete=True)
        assert result.payload == "first writer"
    assert result.revision == original.revision + 1
    assert (await controls.get(original.id)).revision == result.revision + 1


async def test_reissued_code_can_close_and_reopen_without_replaying_membership(context):
    service, controls, companion, auth, _ = context
    run = await create_run(service)
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth", "open_browser"):
        run = await command(service, run, action)
    auth.snapshot = auth.snapshot.model_copy(update={"flow_id": "oauth-2", "user_code": "NEW-CODE"})
    run = await command(service, run, "observe_auth")
    assert run.last_code == "auth_browser_code_changed"
    assert "close_browser" in run.allowed_actions
    assert "finish" not in run.allowed_actions
    run = await command(service, run, "close_browser")
    assert run.phase == "needs_attention"
    assert "prepare_session" in run.allowed_actions and "open_browser" not in run.allowed_actions
    assert (await controls.active()).id == run.id
    run = await command(service, run, "prepare_session")
    assert run.phase == "auth_prepared" and "open_browser" in run.allowed_actions
    companion.open_browser = AsyncMock(wraps=companion.open_browser)
    run = await command(service, run, "open_browser")
    assert run.phase == "auth_browser_opened"
    assert companion.open_browser.call_args.args[0].user_code == "NEW-CODE"
    assert companion.calls.count("start") == 1


@pytest.mark.parametrize("code", ["invite_timeout", "member_add_failed", "delete_failed"])
async def test_admitted_membership_failure_cannot_be_finished_as_a_reset(context, code):
    service, controls, companion, _, _ = context
    run = await command(service, await create_run(service), "start")
    companion.snapshot = companion.snapshot.model_copy(
        update={"stage": "failed", "code": code, "membership_state": "unknown"}
    )
    run = await command(service, run, "observe_membership")
    assert run.phase == "needs_attention"
    assert "finish" not in run.allowed_actions
    with pytest.raises(ControlConflict, match="transition_not_allowed"):
        await command(service, run, "finish")
    assert (await controls.active()).id == run.id
    assert "finalize" not in companion.calls


async def test_partial_target_collision_blocks_old_auth_deletion():
    request = prepare_request()
    assert request.removed_email is not None
    repo = FakeRepository(
        [account("old-local", request.removed_email, request.workspace_account_id, AccountStatus.ACTIVE)]
    )
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repo, oauth, MemberAuthHandoffStore())
    prepared = await service.prepare(request)
    target = account("target-local", request.target_email, request.workspace_account_id, AccountStatus.ACTIVE)
    collision = account("collision", request.target_email, request.workspace_account_id, AccountStatus.ACTIVE)
    collision.chatgpt_user_id = "user-DifferentPrincipal"
    repo.accounts.extend([target, collision])
    oauth.status = "success"
    result = await service.advance(prepared.handoff_id)
    assert result is not None
    assert result.error_code == "ambiguous_target_auth"
    assert repo.deleted == []
