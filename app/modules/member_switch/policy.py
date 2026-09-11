from __future__ import annotations

from app.modules.member_switch.repository import ControlConflict
from app.modules.member_switch.schemas import Action, Identity, Operation, RunState

AUTH_READY_CODES = frozenset(
    {
        "member_added",
        "member_added_automatically",
        "already_active",
        "oauth_recovery_authorized",
    }
)

_PRE_MEMBERSHIP_FAILURE_STAGES = frozenset({"queued", "confirming_personal", "failed"})
_OWNER_CONFIRMATION_CODE = "confirming_owner_personal_before_membership_change"
_KNOWN_OWNER_PREFLIGHT_FAILURES = frozenset(
    {"ego_owner_profile_login_required", "ego_owner_identity_mismatch", "ego_owner_identity_unavailable"}
)



def require_operation_identity(identity: Identity, operation_id: str, operation: Operation) -> None:
    if (
        operation.operation_id != operation_id
        or operation.member_switch_operation_id != operation_id
        or operation.workspace_id != identity.workspace_id
        or operation.workspace_account_id != identity.workspace_account_id
        or operation.target_email.casefold() != identity.target_email.casefold()
        or operation.target_user_id != identity.target_user_id
    ):
        raise ControlConflict("operation_identity_mismatch")


def membership_confirmed(operation: Operation) -> bool:
    return (
        operation.stage == "completed" and operation.membership_state == "active" and operation.code in AUTH_READY_CODES
    )


def pre_membership_failure_confirmed(operation: Operation) -> bool:
    """Return true only when durable operation evidence proves mutation never started."""

    if (
        operation.stage != "failed"
        or operation.membership_state != "unknown"
        or operation.invitation_settlement is not None
        or not operation.trace
    ):
        return False
    if not any(entry.code == _OWNER_CONFIRMATION_CODE for entry in operation.trace):
        return False
    if not all(
        entry.stage in _PRE_MEMBERSHIP_FAILURE_STAGES and entry.action is None and entry.status is None
        for entry in operation.trace
    ):
        return False
    if operation.code == "personal_switch_not_confirmed":
        return True  # Preserve the existing narrow legacy closeout contract.
    if operation.code not in _KNOWN_OWNER_PREFLIGHT_FAILURES:
        return False
    # New Ego failures require the complete producer trace, never a truncated tail
    # or a recipient-stage failure after owner confirmation. Unknown effects stay retained.
    expected = [
        ("queued", "queued"),
        ("confirming_personal", _OWNER_CONFIRMATION_CODE),
        ("confirming_personal", operation.code),
        ("failed", operation.code),
    ]
    return [(entry.stage, entry.code) for entry in operation.trace] == expected and [
        entry.sequence for entry in operation.trace
    ] == [1, 2, 3, 4]


def allowed_actions(state: RunState, pending_action: str | None) -> list[Action]:
    if pending_action:
        return ["cancel"] if pending_action == "preview" else ["reconcile"]
    if state.phase == "completed":
        return []
    if state.phase == "previewed":
        return ["start", "cancel"] if state.preview and state.preview.ready else ["cancel"]
    actions: list[Action] = []
    if state.operation_id:
        actions.append("observe_membership")
    if state.phase == "membership_confirmed" and not state.handoff_id:
        actions.append("prepare_session")
    if state.phase == "session_prepared" and not state.handoff_id:
        actions.append("prepare_session")
        actions.append("prepare_auth")
    if state.handoff_id:
        actions.append("observe_auth")
        if state.auth_state not in {"completed", "failed"}:
            actions.append("advance_auth")
            if not state.browser_operation_id:
                # Recheck the same member session without issuing another OAuth handoff.
                actions.append("prepare_session")
                # A remembered browser flow means the prior target was closed or an
                # open attempt failed. Reopen only after prepare_session clears it.
                if state.phase == "auth_prepared" and state.browser_flow_id is None:
                    actions.append("open_browser")
    if state.browser_operation_id:
        actions.append("close_browser")
    elif state.phase == "auth_confirmed":
        actions.append("finish")
    if (
        state.phase == "needs_attention"
        and state.operation is not None
        and not state.handoff_id
        and not state.browser_operation_id
        and pre_membership_failure_confirmed(state.operation)
    ):
        actions.append("finish")
    if state.phase == "failed" and not state.operation_id and not state.handoff_id and not state.browser_operation_id:
        actions.append("finish")
    return actions
