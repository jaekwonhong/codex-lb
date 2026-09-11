from __future__ import annotations

import hashlib

from app.modules.member_switch.repository import ControlConflict, ControlRecord
from app.modules.member_switch.schemas import ParticipantReceipt, ParticipantRequest, RunState


def participant_fingerprint(request: ParticipantRequest) -> str:
    identity = request.identity
    fields = (
        request.command_id,
        request.client_flow_id,
        request.action,
        request.member_switch_operation_id,
        identity.workspace_id,
        identity.workspace_account_id,
        identity.preset_id,
        identity.target_email,
        identity.target_user_id,
        identity.catalog_fingerprint,
        request.browser_operation_id,
        request.verification_url,
        request.user_code,
    )
    digest = hashlib.sha256()
    for field in fields:
        value = (field or "").encode("utf-8")
        digest.update(str(len(value)).encode("ascii") + b":" + value)
    return digest.hexdigest()


def accept_participant(record: ControlRecord, state: RunState, receipt: ParticipantReceipt) -> RunState:
    if (
        receipt.command_id != record.command_id
        or receipt.client_flow_id != state.id
        or receipt.action != record.pending_action
        or receipt.member_switch_operation_id != state.operation_id
        or receipt.identity != state.identity
        or not state.participant_request_hash
        or receipt.request_hash != state.participant_request_hash
        or receipt.browser_operation_id != (state.browser_operation_id if receipt.action == "close_browser" else None)
    ):
        raise ControlConflict("participant_receipt_identity_mismatch")
    if receipt.state != "completed":
        raise ControlConflict("participant_outcome_still_unknown")
    results = [receipt.session, receipt.browser, receipt.close]
    if sum(value is not None for value in results) != 1:
        raise ControlConflict("participant_receipt_invalid")
    if receipt.action == "prepare_session":
        ready = receipt.session
        if ready is None or ready.outcome_unknown:
            raise ControlConflict("participant_outcome_still_unknown")
        if ready.ready and ready.target_email != state.identity.target_email:
            raise ControlConflict("recipient_identity_mismatch")
        phase = (
            "auth_prepared"
            if state.handoff_id and ready.ready
            else "needs_attention"
            if state.handoff_id
            else "session_prepared"
            if ready.ready
            else "membership_confirmed"
        )
        return state.model_copy(
            update={
                "phase": phase,
                "last_code": ready.code,
                # A prior close/open failure keeps browser_flow_id as the durable
                # recheck gate. Only an exact successful session check clears it.
                "browser_flow_id": None if state.handoff_id and ready.ready else state.browser_flow_id,
            }
        )
    if receipt.action == "open_browser":
        browser = receipt.browser
        if browser is None or browser.outcome_unknown:
            raise ControlConflict("participant_outcome_still_unknown")
        if browser.accepted != bool(browser.browser_operation_id):
            raise ControlConflict("invalid_browser_receipt")
        if browser.target_email and browser.target_email.casefold() != state.identity.target_email:
            raise ControlConflict("browser_identity_mismatch")
        if browser.accepted and not browser.target_email:
            raise ControlConflict("browser_identity_mismatch")
        return state.model_copy(
            update={
                "browser_operation_id": browser.browser_operation_id,
                # Preserve the attempted OAuth flow even for a known open failure.
                # It prevents direct reopen until an explicit session recheck succeeds.
                "browser_flow_id": state.browser_flow_id,
                "phase": "auth_browser_opened" if browser.accepted else "needs_attention",
                "last_code": browser.code,
            }
        )
    close = receipt.close
    if close is None or close.outcome_unknown:
        raise ControlConflict("participant_outcome_still_unknown")
    state = state.model_copy(update={"last_code": close.code})
    if close.closed:
        return state.model_copy(
            update={
                "browser_operation_id": None,
                # Preserve the closed flow as the authority that a fresh exact-member
                # login check is required before another browser open.
                "browser_flow_id": state.browser_flow_id,
                "phase": "auth_confirmed" if state.auth_state == "completed" else "needs_attention",
            }
        )
    return state
