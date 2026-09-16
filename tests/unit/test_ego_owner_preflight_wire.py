"""C#-generated preflight traces are the cross-language permission inputs."""

import json
from pathlib import Path

import pytest

from app.modules.member_switch.policy import allowed_actions, pre_membership_failure_confirmed
from app.modules.member_switch.schemas import Identity, Operation, RunState

_OPERATIONS = json.loads((Path(__file__).parents[1] / "fixtures/ego_owner_preflight_failures.json").read_text())
_KNOWN_CODES = {"ego_owner_profile_login_required", "ego_owner_identity_mismatch", "ego_owner_identity_unavailable"}


@pytest.mark.parametrize("raw", _OPERATIONS, ids=[row["code"] for row in _OPERATIONS])
def test_actual_csharp_preflight_trace_controls_explicit_closeout(raw):
    operation = Operation.model_validate(raw)
    permitted = operation.code in _KNOWN_CODES
    assert pre_membership_failure_confirmed(operation) is permitted
    state = RunState(
        control_protocol="managed_member_switch_v1",
        id="synthetic-wire-run",
        create_request_hash="a" * 64,
        identity=Identity(
            workspace_id=operation.workspace_id,
            workspace_account_id=operation.workspace_account_id,
            preset_id="cdp-1-target",
            target_email=operation.target_email,
            target_user_id=operation.target_user_id,
            catalog_fingerprint="a" * 64,
        ),
        phase="needs_attention",
        last_code=operation.code,
        updated_at=operation.updated_at,
        operation_id=operation.operation_id,
        operation=operation,
    )
    assert ("finish" in allowed_actions(state, None)) is permitted
    # Even valid preflight evidence cannot authorize closeout while another effect is pending.
    assert allowed_actions(state, "start") == ["reconcile"]
    assert "finish" not in allowed_actions(state.model_copy(update={"handoff_id": "retained-handoff"}), None)
    assert "finish" not in allowed_actions(state.model_copy(update={"browser_operation_id": "retained-browser"}), None)
