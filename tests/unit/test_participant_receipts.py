from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.member_switch.participants import participant_fingerprint
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.schemas import ParticipantReceipt, ParticipantRequest
from app.modules.member_switch.service import MemberSwitchService
from tests.unit.test_member_switch_control import command, create_run
from tests.unit.test_member_switch_control import context as context

pytestmark = pytest.mark.unit


async def before_action(context, action):
    service = context[0]
    run = await create_run(service)
    steps = ["start", "observe_membership", "prepare_session", "prepare_auth", "open_browser"]
    for step in steps:
        if step == action:
            break
        run = await command(service, run, step)
    return run


@pytest.mark.parametrize(
    "action,phase",
    [
        ("prepare_session", "session_prepared"),
        ("open_browser", "auth_browser_opened"),
        ("close_browser", "needs_attention"),
    ],
)
async def test_lost_participant_response_recovers_from_exact_receipt_without_replay(context, action, phase):
    service, controls, companion, auth, sessions = context
    run = await before_action(context, action)
    companion.lose_participant = True
    before_auth = len(auth.calls)
    with pytest.raises(ControlConflict, match="synthetic_response_lost"):
        await command(service, run, action)
    restarted = MemberSwitchService(MemberSwitchControlRepository(sessions), companion, auth)
    run = await restarted.get(run.id)
    assert run.phase == "outcome_unknown" and run.allowed_actions == ["reconcile"]
    calls = list(companion.calls)
    recovered = await command(restarted, run, "reconcile")
    assert recovered.phase == phase and recovered.pending_action is None
    expected_read = "reconcile_participant_receipt" if action == "close_browser" else "participant_receipt"
    assert companion.calls == calls + [expected_read]
    assert (await controls.active()).id == run.id
    if action == "prepare_session":
        assert len(auth.calls) == before_auth
        assert "prepare_auth" in recovered.allowed_actions
    if action == "close_browser":
        assert "prepare_session" in recovered.allowed_actions
        assert "open_browser" not in recovered.allowed_actions


@pytest.mark.parametrize("action", ["prepare_session", "open_browser", "close_browser"])
async def test_parent_commit_failure_is_reconciled_without_another_participant_call(context, monkeypatch, action):
    service, controls, companion, _, _ = context
    run = await before_action(context, action)
    save = controls.save

    async def fail_completion(current, payload, **kwargs):
        if kwargs.get("complete"):
            raise OSError("synthetic parent commit failure")
        return await save(current, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(controls, "save", fail_completion)
        with pytest.raises(OSError):
            await command(service, run, action)
    run = await service.get(run.id)
    count = companion.calls.count(action)
    run = await command(service, run, "reconcile")
    assert run.pending_action is None
    assert companion.calls.count(action) == count


@pytest.mark.parametrize("fault", ["missing", "pending", "hash", "command", "operation", "run", "identity", "action"])
async def test_missing_pending_or_mismatched_evidence_never_releases_or_replays(context, fault):
    service, controls, companion, _, _ = context
    run = await before_action(context, "open_browser")
    companion.lose_participant = True
    with pytest.raises(ControlConflict):
        await command(service, run, "open_browser")
    record = await controls.get(run.id)
    receipt = companion.participant_receipts[record.command_id]
    if fault == "missing":
        del companion.participant_receipts[record.command_id]
    else:
        updates = {
            "pending": {"state": "pending", "browser": None},
            "hash": {"request_hash": "0" * 64},
            "command": {"command_id": str(uuid4())},
            "operation": {"member_switch_operation_id": "foreign"},
            "run": {"client_flow_id": str(uuid4())},
            "action": {"action": "prepare_session"},
            "identity": {"identity": receipt.identity.model_copy(update={"target_user_id": "user-Foreign"})},
        }[fault]
        companion.participant_receipts[record.command_id] = receipt.model_copy(update=updates)
    with pytest.raises(ControlConflict):
        await command(service, await service.get(run.id), "reconcile")
    assert (await controls.active()).id == run.id
    assert (await service.get(run.id)).pending_action == "open_browser"
    assert companion.calls.count("open_browser") == 1


async def test_fingerprint_is_committed_before_participant_call_and_contains_no_user_code(context, monkeypatch):
    service, controls, companion, _, _ = context
    run = await before_action(context, "open_browser")
    original = companion.participant

    async def inspect(request):
        record = await controls.get(run.id)
        payload = json.loads(record.payload)
        assert payload["participant_request_hash"] == participant_fingerprint(request)
        assert "TEST-CODE" not in record.payload
        assert record.pending_action == "open_browser"
        return await original(request)

    monkeypatch.setattr(companion, "participant", inspect)
    await command(service, run, "open_browser")


async def test_old_companion_capability_is_refused_before_membership_mutation(context, monkeypatch):
    service, _, companion, _, _ = context
    catalog = await companion.catalog()
    old = catalog.model_copy(
        update={"capabilities": [c for c in catalog.capabilities if c != "durable_participant_commands_v1"]}
    )
    monkeypatch.setattr(companion, "catalog", AsyncMock(return_value=old))
    with pytest.raises(ControlConflict, match="protocol_upgrade_required"):
        await create_run(service)
    assert "start" not in companion.calls and "preview" not in companion.calls


async def test_completed_no_effect_participant_rejection_clears_parent_intent(context, monkeypatch):
    service, controls, companion, _, _ = context
    run = await before_action(context, "prepare_session")

    async def reject(request):
        receipt = ParticipantReceipt.model_validate(
            {
                "schemaVersion": 1,
                "commandId": request.command_id,
                "clientFlowId": request.client_flow_id,
                "action": request.action,
                "memberSwitchOperationId": request.member_switch_operation_id,
                "identity": request.identity.model_dump(mode="json", by_alias=True),
                "requestHash": participant_fingerprint(request),
                "state": "completed",
                "code": "participant_owner_mismatch",
                "recordedAt": "2026-09-06T00:00:00Z",
                "browserOperationId": None,
                "session": {
                    "ready": False,
                    "code": "participant_owner_mismatch",
                    "targetEmail": request.identity.target_email,
                    "reauthenticated": False,
                    "trace": ["participant_owner_mismatch"],
                    "outcomeUnknown": False,
                },
            }
        )
        companion.participant_receipts[request.command_id] = receipt
        return receipt

    monkeypatch.setattr(companion, "participant", reject)
    rejected = await command(service, run, "prepare_session")
    assert rejected.pending_action is None
    assert rejected.phase == "membership_confirmed"
    assert rejected.last_code == "participant_owner_mismatch"
    assert (await controls.active()).id == run.id
    assert "prepare_session" in rejected.allowed_actions


def test_real_csharp_request_fingerprints_and_typed_results_agree():
    path = Path(
        os.environ.get("PARTICIPANT_WIRE_FIXTURE", str(Path(__file__).parents[1] / "fixtures/participant_wire.json"))
    )
    pairs = json.loads(path.read_text())
    assert len(pairs) == 4
    for pair in pairs:
        request = ParticipantRequest.model_validate(pair["request"])
        receipt = ParticipantReceipt.model_validate(pair["receipt"])
        assert participant_fingerprint(request) == receipt.request_hash
        assert receipt.state == "completed"
        assert receipt.command_id == request.command_id and receipt.identity == request.identity
    assert [pair["receipt"]["action"] for pair in pairs] == [
        "prepare_session",
        "open_browser",
        "close_browser",
        "prepare_session",
    ]
    assert pairs[-1]["receipt"]["code"] == "participant_owner_mismatch"
    assert pairs[-1]["receipt"]["session"]["ready"] is False
