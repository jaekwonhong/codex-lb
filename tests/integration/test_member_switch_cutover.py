from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.db.models import Account, MemberSwitchControlRecord
from app.modules.member_switch.repository import MemberSwitchControlRepository
from tests.integration.test_member_switch_participants import ROOT
from tests.integration.test_member_switch_participants import integration as integration

pytestmark = pytest.mark.integration


async def create_response(test):
    target = test.catalog.entries[0]
    return await test.client.post(
        ROOT,
        json={
            "runId": str(uuid4()),
            "workspaceId": target.workspace_id,
            "presetId": target.preset_id,
            "catalogFingerprint": test.catalog.fingerprint(),
        },
    )


async def test_quarantined_auth_without_a_run_blocks_new_work(integration):
    async with integration.sessions() as session:
        await session.execute(
            update(Account).where(Account.id == "outgoing").values(deactivation_reason="member_auth_handoff_quarantine")
        )
        await session.commit()
    response = await create_response(integration)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "quarantined_auth_retained"
    assert integration.wire.calls == [] and integration.oauth.starts == []
    assert (await integration.account("outgoing")).deactivation_reason == "member_auth_handoff_quarantine"


async def test_old_run_is_visible_but_cannot_be_adopted_by_new_commands(integration):
    run = await integration.create()
    async with integration.sessions() as session:
        row = await session.get(MemberSwitchControlRecord, run["id"])
        payload = json.loads(row.payload)
        payload.pop("control_protocol", None)
        payload.pop("controlProtocol", None)
        row.payload = json.dumps(payload)
        original = row.payload
        await session.commit()
    calls = list(integration.wire.calls)
    observed = await integration.read(run)
    assert observed["allowedActions"] == []
    assert observed["lastCode"] == "legacy_run_review_required"
    response = await integration.command(run, "start", expected=409)
    assert response["error"]["code"] == "legacy_run_review_required"
    async with integration.sessions() as session:
        assert (await session.get(MemberSwitchControlRecord, run["id"])).payload == original
    assert integration.wire.calls == calls


async def test_unreadable_orphan_handoff_blocks_new_work_without_repair(integration):
    controls = MemberSwitchControlRepository(integration.sessions)
    await controls.create("handoff:orphan", "handoff", "{broken", own_scope=False)
    response = await create_response(integration)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stored_handoff_review_required"
    assert (await controls.get("handoff:orphan")).payload == "{broken"
    assert integration.wire.calls == []


@pytest.mark.parametrize("path", ["/rotation-events/claim", "/catalog-members"])
async def test_legacy_backend_writes_are_rejected_before_parsing_or_constructing_writers(integration, path):
    response = await integration.client.post(
        "/api/member-auth-handoffs" + path, content="not json", headers={"Content-Type": "application/octet-stream"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "managed_run_command_required"
    assert integration.wire.calls == [] and integration.oauth.starts == []


async def test_admission_diagnostics_are_read_only_and_identify_retained_records(integration, monkeypatch):
    import app.dependencies as dependencies

    async with integration.sessions() as session:
        await session.execute(
            update(Account).where(Account.id == "outgoing").values(deactivation_reason="member_auth_handoff_quarantine")
        )
        await session.commit()

    def must_not_construct(*args, **kwargs):
        raise AssertionError("No OAuth writer may be constructed by admission reads")

    monkeypatch.setattr(dependencies, "OauthService", must_not_construct)
    integration.statements.clear()
    for _ in range(3):
        response = await integration.client.get(ROOT + "/admission")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "canCreate": False,
            "blockers": [{"kind": "account", "recordId": "outgoing", "code": "quarantined_auth_retained"}],
        }
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in integration.statements)
    assert integration.wire.calls == []


async def test_new_quarantine_after_preview_is_rechecked_before_membership_start(integration):
    run = await integration.create()
    async with integration.sessions() as session:
        await session.execute(
            update(Account).where(Account.id == "outgoing").values(deactivation_reason="member_auth_handoff_quarantine")
        )
        await session.commit()
    calls = list(integration.wire.calls)
    response = await integration.command(run, "start", expected=409)
    assert response["error"]["code"] == "quarantined_auth_retained"
    assert (await integration.read(run))["revision"] == run["revision"]
    assert integration.wire.calls == calls


async def test_orphaned_current_run_cannot_execute_without_active_scope(integration):
    run = await integration.create()
    async with integration.sessions() as session:
        await session.execute(
            update(MemberSwitchControlRecord).where(MemberSwitchControlRecord.id == run["id"]).values(active_scope=None)
        )
        await session.commit()
    observed = await integration.read(run)
    assert observed["allowedActions"] == []
    assert observed["lastCode"] == "orphan_run_retained"
    before = list(integration.wire.calls)
    await integration.command(run, "start", expected=409)
    assert (await create_response(integration)).status_code == 409
    assert integration.wire.calls == before


async def test_missing_companion_fence_capability_blocks_before_any_write(integration):
    integration.wire.examples["catalog"]["capabilities"].remove("managed_member_switch_v1")
    response = await create_response(integration)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "companion_protocol_upgrade_required"
    assert all(method == "GET" for method, _, _ in integration.wire.calls)


async def test_completed_unversioned_history_is_not_adopted_or_a_new_run_blocker(integration):
    run = await integration.create()
    run = await integration.command(run, "cancel")
    async with integration.sessions() as session:
        row = await session.get(MemberSwitchControlRecord, run["id"])
        payload = json.loads(row.payload)
        payload.pop("control_protocol", None)
        row.payload = json.dumps(payload)
        await session.commit()
    observed = await integration.read(run)
    assert observed["phase"] == "completed" and observed["allowedActions"] == []
    assert (await create_response(integration)).status_code == 200
