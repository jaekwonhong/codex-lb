"""C# driver/controller/store receipts consumed by the actual Python state machine.

Regenerate the synthetic fixture with the C# Emit_actual_close_receipts test and
EGO_REVIEW_WIRE_OUT pointing to tests/fixtures/member_switch/ego_close_receipts.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.modules.member_switch.participants import accept_participant, participant_fingerprint
from app.modules.member_switch.policy import allowed_actions
from app.modules.member_switch.repository import ControlConflict, ControlRecord
from app.modules.member_switch.schemas import CONTROL_PROTOCOL, ParticipantReceipt, ParticipantRequest, RunState

pytestmark = pytest.mark.unit


def fixture():
    path = Path(__file__).parents[1] / "fixtures/member_switch/ego_close_receipts.json"
    wire = json.loads(path.read_text())
    request = ParticipantRequest.model_validate(wire["request"])
    pending = ParticipantReceipt.model_validate(wire["pending"])
    settled = ParticipantReceipt.model_validate(wire["settled"])
    state = RunState(
        control_protocol=CONTROL_PROTOCOL,
        id=request.client_flow_id,
        create_request_hash="a" * 64,
        identity=request.identity,
        phase="auth_browser_opened",
        last_code="opened",
        updated_at=datetime.now(timezone.utc),
        operation_id=request.member_switch_operation_id,
        handoff_id="same-handoff",
        auth_state="device_code_issued",
        browser_operation_id=request.browser_operation_id,
        browser_flow_id="same-device-flow",
        participant_request_hash=participant_fingerprint(request),
    )
    record = ControlRecord(
        state.id,
        "member-switch",
        "member-switch",
        1,
        state.model_dump_json(),
        "close_browser",
        request.command_id,
        "b" * 64,
    )
    return request, pending, settled, record, state


def test_real_csharp_pending_and_settled_receipts_have_python_fingerprint():
    request, pending, settled, _, _ = fixture()
    assert pending.request_hash == settled.request_hash == participant_fingerprint(request)
    assert pending.state == "pending" and pending.close is None
    assert settled.state == "completed" and settled.close.closed


def test_real_pending_close_cannot_release_or_replay():
    _, pending, _, record, state = fixture()
    with pytest.raises(ControlConflict, match="participant_outcome_still_unknown"):
        accept_participant(record, state, pending)
    assert allowed_actions(state, record.pending_action) == ["reconcile"]


def test_real_settled_close_preserves_handoff_and_requires_exact_session_recovery():
    _, _, settled, record, state = fixture()
    after = accept_participant(record, state, settled)
    assert after.phase == "needs_attention" and after.browser_operation_id is None
    assert after.handoff_id == state.handoff_id
    assert after.browser_flow_id == state.browser_flow_id
    actions = allowed_actions(after, None)
    assert "prepare_session" in actions and "open_browser" not in actions
    assert "prepare_auth" not in actions and "finish" not in actions


def test_foreign_identity_is_not_accepted_as_closed():
    _, _, settled, record, state = fixture()
    foreign = settled.model_copy(
        update={"identity": settled.identity.model_copy(update={"target_email": "foreign@example.com"})}
    )
    with pytest.raises(ControlConflict, match="participant_receipt_identity_mismatch"):
        accept_participant(record, state, foreign)
