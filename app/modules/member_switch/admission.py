from __future__ import annotations

from pydantic import ValidationError

from app.modules.member_auth_handoff.durable import HandoffEnvelope, handoff_id_for_operation
from app.modules.member_switch.repository import (
    GLOBAL_SCOPE,
    ControlConflict,
    ControlRecord,
    MemberSwitchControlRepository,
)
from app.modules.member_switch.rotation_plan import SCHEDULE_BINDING_ID, CanaryPlan
from app.modules.member_switch.schemas import (
    AUTH_ENROLLMENT_PROTOCOL,
    CONTROL_PROTOCOL,
    ROTATION_CONTROLLER_PROTOCOL,
    AdmissionBlocker,
    AuthEnrollmentState,
    LocalAdmission,
    RotationControllerState,
    RunState,
)
from app.modules.workspace_member_controller.mutation_models import MembershipMutationState


def _is_own_enrollment_child(
    record: ControlRecord,
    envelope: HandoffEnvelope,
    parent: ControlRecord | None,
    owning_run_id: str | None,
) -> bool:
    """A settled child command is continuation evidence, not competing work."""
    if (
        parent is None
        or parent.id != owning_run_id
        or parent.kind != "auth_enrollment"
        or parent.active_scope != GLOBAL_SCOPE
        or parent.pending_action
        or record.active_scope is not None
        or record.pending_action
        or not envelope.result_ready
        or not record.command_id
        or envelope.result_command_id != record.command_id
    ):
        return False
    try:
        state = AuthEnrollmentState.model_validate_json(parent.payload)
    except ValidationError:
        return False
    handoff, identity = envelope.handoff, state.identity
    request = handoff.request
    return (
        state.id == parent.id
        and state.control_protocol == AUTH_ENROLLMENT_PROTOCOL
        and state.phase in {"auth_prepared", "auth_browser_opened"}
        and state.operation_id == "oauth-enrollment:" + state.id
        and state.handoff_id == handoff.handoff_id == handoff_id_for_operation(state.operation_id)
        and request.member_switch_operation_id == state.operation_id
        and request.preset_id == identity.preset_id
        and request.workspace_account_id == identity.workspace_account_id
        and request.target_email.casefold() == identity.target_email.casefold()
        and request.target_user_id == identity.target_user_id
        and request.catalog_fingerprint == identity.catalog_fingerprint
        and request.preserve_other_auth
        and request.removed_email is None
        and request.removed_user_id is None
        and handoff.old_account_id is None
        and not handoff.old_auth_deleted
    )


async def local_admission(
    controls: MemberSwitchControlRepository, *, owning_run_id: str | None = None
) -> LocalAdmission:
    """Observe existing evidence; never adopt, normalize or clear stored records."""
    snapshot = await controls.admission_snapshot()
    records_by_id = {record.id: record for record in snapshot.records}
    blockers: list[AdmissionBlocker] = []
    for record in snapshot.records:
        code: str | None = None
        if record.kind == "run":
            try:
                state = RunState.model_validate_json(record.payload)
            except ValidationError:
                code = "stored_run_review_required"
            else:
                if state.id != record.id:
                    code = "stored_run_review_required"
                elif (
                    record.id == owning_run_id
                    and record.active_scope == GLOBAL_SCOPE
                    and state.control_protocol == CONTROL_PROTOCOL
                ):
                    continue
                elif record.active_scope is not None or record.pending_action or state.phase != "completed":
                    code = (
                        "legacy_run_review_required" if state.control_protocol != CONTROL_PROTOCOL else "run_retained"
                    )
        elif record.kind == "handoff":
            try:
                envelope = HandoffEnvelope.model_validate_json(record.payload)
            except ValidationError:
                code = "stored_handoff_review_required"
            else:
                if record.id != "handoff:" + envelope.handoff.handoff_id:
                    code = "stored_handoff_review_required"
                elif record.pending_action:
                    code = "handoff_retained"
                elif _is_own_enrollment_child(
                    record, envelope, records_by_id.get(envelope.managed_run_id), owning_run_id
                ):
                    continue
                elif envelope.handoff.state == "failed":
                    parent = records_by_id.get(envelope.managed_run_id)
                    if parent is not None and parent.kind == "auth_enrollment":
                        try:
                            enrollment = AuthEnrollmentState.model_validate_json(parent.payload)
                        except ValidationError:
                            code = "stored_handoff_review_required"
                        else:
                            if enrollment.phase != "completed":
                                code = "handoff_retained"
                    else:
                        code = "handoff_retained"
                elif envelope.handoff.state != "completed":
                    code = "handoff_retained"
        elif record.kind == "auth_enrollment":
            try:
                state = AuthEnrollmentState.model_validate_json(record.payload)
            except ValidationError:
                code = "stored_auth_enrollment_review_required"
            else:
                if state.id != record.id:
                    code = "stored_auth_enrollment_review_required"
                elif (
                    record.id == owning_run_id
                    and record.active_scope == GLOBAL_SCOPE
                    and state.control_protocol == AUTH_ENROLLMENT_PROTOCOL
                ):
                    continue
                elif record.active_scope is not None or record.pending_action or state.phase != "completed":
                    code = (
                        "legacy_auth_enrollment_review_required"
                        if state.control_protocol != AUTH_ENROLLMENT_PROTOCOL
                        else "auth_enrollment_retained"
                    )
        elif record.kind == "rotation":
            try:
                state = RotationControllerState.model_validate_json(record.payload)
            except ValidationError:
                code = "stored_rotation_review_required"
            else:
                child = records_by_id.get(state.member_switch_run_id)
                effect_may_have_crossed = state.phase != "completed" and (
                    state.remove_state in {"unknown", "confirmed"}
                    or state.invite_state in {"unknown", "confirmed"}
                    or state.phase
                    in {
                        "removing",
                        "removal_effect_unknown",
                        "removal_confirmed",
                        "inviting",
                        "invite_effect_unknown",
                        "invite_sent",
                        "waiting_membership",
                        "finalizing",
                    }
                )
                if (
                    state.id != record.id
                    or state.control_protocol != ROTATION_CONTROLLER_PROTOCOL
                    or record.active_scope is not None
                    or record.pending_action is not None
                ):
                    code = "stored_rotation_review_required"
                elif effect_may_have_crossed and (
                    child is None or child.kind != "run" or child.active_scope != GLOBAL_SCOPE
                ):
                    code = "rotation_effect_owner_missing"
        elif record.kind == "rotation_schedule":
            try:
                CanaryPlan.model_validate_json(record.payload)
            except ValidationError:
                code = "stored_rotation_schedule_review_required"
            else:
                if record.id != SCHEDULE_BINDING_ID or record.active_scope is not None or record.pending_action:
                    code = "stored_rotation_schedule_review_required"
        elif record.kind == "controller_membership_mutation":
            try:
                state = MembershipMutationState.model_validate_json(record.payload)
            except ValidationError:
                code = "stored_controller_mutation_review_required"
            else:
                if state.operation_id != record.id:
                    code = "stored_controller_mutation_review_required"
                elif (
                    record.active_scope is not None
                    or record.pending_action
                    or state.phase not in {"completed", "failed"}
                ):
                    code = "controller_mutation_retained"
        else:
            code = "unknown_control_record"
        if code:
            blockers.append(AdmissionBlocker(kind=record.kind, record_id=record.id, code=code))
    blockers.extend(
        AdmissionBlocker(kind="account", record_id=id, code="quarantined_auth_retained")
        for id in snapshot.quarantined_account_ids
    )
    return LocalAdmission(can_create=not blockers, blockers=blockers)


async def require_new_work_admission(
    controls: MemberSwitchControlRepository, *, owning_run_id: str | None = None
) -> None:
    admission = await local_admission(controls, owning_run_id=owning_run_id)
    if admission.blockers:
        raise ControlConflict(admission.blockers[0].code)
