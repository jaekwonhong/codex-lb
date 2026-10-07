from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.modules.member_switch.repository import ControlRecord
from app.modules.member_switch.schemas import (
    CANARY_PARTIAL_RECOVERY_CAPABILITY,
    CompanionAdmission,
    FinalizeReceipt,
    InvitationSettlement,
    Operation,
    OperationTraceEntry,
    StartReceipt,
)
from app.modules.workspace_member_controller.account_state import OpenCodexAccountState
from app.modules.workspace_member_controller.domain import (
    Catalog,
    Member,
    MembershipObservation,
    MembershipObservationMember,
    Workspace,
)
from app.modules.workspace_member_controller.legacy_partial_recovery_runner import (
    _exact_completed_recovery,
    _exact_partial_parent,
    run_recovery,
)
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationAdmissionEvidence,
    MembershipMutationReceipt,
    MembershipMutationSpec,
    MembershipMutationState,
    MembershipRecoveryAttempt,
    MembershipSubject,
)
from app.modules.workspace_member_controller.persistence import MembershipMutationJournalEntry

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)
PARENT_FLOW = "11111111-1111-4111-8111-111111111111"
CHILD_FLOW = "33333333-3333-4333-8333-333333333333"
PARENT_OPERATION = "companion-parent"
CHILD_OPERATION = "companion-recovery"
WORKSPACE_ACCOUNT = "85d8ee33-bc27-4413-b3dc-24605885d5b0"
FINGERPRINT = "a" * 64


def subject(preset: str, user: str) -> MembershipSubject:
    return MembershipSubject(preset_id=preset, email=f"{preset}@example.com", user_id=user)


def state() -> MembershipMutationState:
    mutation = MembershipMutationSpec(
        action="switch",
        workspace_id="cdp-2",
        workspace_account_id=WORKSPACE_ACCOUNT,
        catalog_fingerprint=FINGERPRINT,
        incoming=subject("target", "user-Target"),
        outgoing=subject("original", "user-Original"),
    )
    return MembershipMutationState(
        operation_id=PARENT_FLOW,
        mutation=mutation,
        command_fingerprint="b" * 64,
        phase="outcome_unknown",
        last_code="canary_effect_unresolved:acceptance_settlement_not_observed",
        created_at=NOW,
        updated_at=NOW,
        admission=MembershipMutationAdmissionEvidence(
            workspace_id="cdp-2",
            workspace_account_id=WORKSPACE_ACCOUNT,
            catalog_fingerprint=FINGERPRINT,
            membership_observed_at=NOW,
        ),
        receipt=MembershipMutationReceipt(
            operation_id=PARENT_FLOW,
            command_id="22222222-2222-4222-8222-222222222222",
            request_fingerprint="b" * 64,
            action="switch",
            workspace_id="cdp-2",
            workspace_account_id=WORKSPACE_ACCOUNT,
            outcome="outcome_unknown",
            code="canary_effect_unresolved:acceptance_settlement_not_observed",
            observed_at=NOW,
            remove_effect="unknown",
            add_effect="unknown",
            final_membership_confirmed=False,
        ),
    )


def parent_operation(*, pending_invite: str = "invite-target") -> Operation:
    return Operation(
        operation_id=PARENT_OPERATION,
        member_switch_operation_id=PARENT_OPERATION,
        workspace_id="cdp-2",
        workspace_account_id=WORKSPACE_ACCOUNT,
        target_email="target@example.com",
        target_user_id="user-Target",
        stage="failed",
        code="acceptance_settlement_not_observed",
        removed_email="original@example.com",
        removed_user_id="user-Original",
        membership_state="unknown",
        updated_at=NOW,
        trace=[
            OperationTraceEntry(
                sequence=1,
                stage="verifying_removal",
                code="outgoing_workspace_absence_observed",
                at=NOW,
            )
        ],
        invitation_settlement=InvitationSettlement(
            invitation_issued=True,
            automatic_observation_attempts=4,
            automatic_settlement_confirmed=False,
            pending_invitation_id=pending_invite,
            fallback_used=True,
            final_membership_confirmed=False,
            invitation_attempted=True,
            recipient_workspace_refresh_attempts=8,
            recipient_workspace_observed=False,
            invitation_non_effect_confirmed=False,
        ),
    )


def recovery_operation() -> Operation:
    return Operation(
        operation_id=CHILD_OPERATION,
        member_switch_operation_id=CHILD_OPERATION,
        workspace_id="cdp-2",
        workspace_account_id=WORKSPACE_ACCOUNT,
        target_email="original@example.com",
        target_user_id="user-Original",
        stage="completed",
        code="member_added",
        removed_email="target@example.com",
        removed_user_id="user-Target",
        membership_state="active",
        updated_at=NOW,
        trace=[
            OperationTraceEntry(
                sequence=1,
                stage="recovering",
                code="recovery_target_invite_absence_observed",
                at=NOW,
            )
        ],
        invitation_settlement=InvitationSettlement(
            invitation_issued=True,
            automatic_observation_attempts=1,
            automatic_settlement_confirmed=True,
            pending_invitation_id=None,
            fallback_used=False,
            final_membership_confirmed=True,
            invitation_attempted=True,
            recipient_workspace_refresh_attempts=1,
            recipient_workspace_observed=True,
        ),
    )


def catalog() -> Catalog:
    return Catalog(
        enabled=True,
        schema_version=1,
        catalog_fingerprint=FINGERPRINT,
        capabilities=[CANARY_PARTIAL_RECOVERY_CAPABILITY],
        workspaces=[
            Workspace(
                id="cdp-2",
                workspace_account_id=WORKSPACE_ACCOUNT,
                workspace_name="Workspace",
                owner_email="owner@example.com",
                members=[
                    Member(
                        preset_id="original",
                        display_name="original",
                        email="original@example.com",
                        user_id="user-Original",
                    ),
                    Member(
                        preset_id="target",
                        display_name="target",
                        email="target@example.com",
                        user_id="user-Target",
                    ),
                ],
            )
        ],
    )


def account(account_id: str) -> OpenCodexAccountState:
    return OpenCodexAccountState(
        schema_version=1,
        provider="openai",
        account_id=account_id,
        is_main=False,
        credential_generation=1,
        observed_at=1,
        has_credential=True,
        needs_reauth=False,
        paused=True,
        health_status="healthy",
        selection_state="excluded",
        exclusion_reasons=["paused"],
        quota_state="unknown",
        cooldowns=[],
        quota_windows=[],
        state_revision="c" * 64,
    )


class Controls:
    def __init__(self) -> None:
        self.record = ControlRecord(
            id=PARENT_FLOW,
            kind="controller_membership_mutation",
            active_scope="member-switch",
            revision=4,
            payload="{}",
            pending_action="switch",
            command_id="22222222-2222-4222-8222-222222222222",
            command_hash="b" * 64,
        )

    async def active(self):
        return self.record


class Journal:
    def __init__(self, *, prepared: bool = False) -> None:
        initial = state()
        if prepared:
            initial = MembershipMutationState.model_validate(
                initial.model_copy(
                    update={
                        "schema_version": 2,
                        "recovery": MembershipRecoveryAttempt(
                            client_flow_id=UUID(CHILD_FLOW),
                            parent_client_flow_id=UUID(PARENT_FLOW),
                            original=initial.mutation.outgoing,
                            failed_target=initial.mutation.incoming,
                            phase="prepared",
                            prepared_at=NOW,
                        ),
                    }
                ).model_dump()
            )
        self.entry = MembershipMutationJournalEntry(
            operation_id=PARENT_FLOW,
            kind="controller_membership_mutation",
            active_scope="member-switch",
            revision=4,
            state=initial,
            pending_action="switch",
            command_id="22222222-2222-4222-8222-222222222222",
        )

    async def get_mutation(self, operation_id):
        return self.entry if operation_id == PARENT_FLOW else None


class Bindings:
    async def get_exact(self, **kwargs):
        return SimpleNamespace(opencodex_account_id="acct-" + kwargs["preset_id"])


class Accounts:
    async def get(self, account_id):
        return account(account_id)


class Service:
    def __init__(self, controls: Controls, events: list[str]) -> None:
        self.controls = controls
        self.events = events

    async def prepare_partial_recovery(self, operation_id, *, recovery_client_flow_id):
        assert operation_id == PARENT_FLOW
        assert recovery_client_flow_id == CHILD_FLOW
        self.events.append("prepare")
        return SimpleNamespace(recovery=SimpleNamespace(client_flow_id=UUID(CHILD_FLOW)))

    async def complete_partial_recovery(self, operation_id, **kwargs):
        assert operation_id == PARENT_FLOW
        assert kwargs == {
            "recovery_client_flow_id": CHILD_FLOW,
            "companion_operation_id": CHILD_OPERATION,
            "cleanup_confirmed": True,
            "restoration_confirmed": True,
        }
        self.events.append("controller-complete")
        self.controls.record = None
        return SimpleNamespace(phase="recovered")


class Companion:
    def __init__(
        self,
        events: list[str],
        *,
        bad_parent: bool = False,
        child_exists: bool = False,
        finalized: bool = False,
    ) -> None:
        self.events = events
        self.started = child_exists
        self.finalized = finalized
        self.bad_parent = bad_parent
        self.recovery_request = None

    async def lookup(self, client_flow_id):
        if client_flow_id == PARENT_FLOW:
            return StartReceipt(accepted=True, code="operation_retained", operation_id=PARENT_OPERATION)
        if client_flow_id == CHILD_FLOW and self.started:
            return StartReceipt(
                accepted=True,
                code="operation_finalized" if self.finalized else "operation_retained",
                operation_id=CHILD_OPERATION,
            )
        return None

    async def operation(self, operation_id):
        if operation_id == PARENT_OPERATION:
            parent = parent_operation()
            return parent.model_copy(update={"code": "other"}) if self.bad_parent else parent
        assert operation_id == CHILD_OPERATION
        return recovery_operation()

    async def admission(self):
        if self.finalized:
            return CompanionAdmission(can_start=True, code="ready")
        return CompanionAdmission(
            can_start=False,
            code="managed_flow_retained",
            operation_id=PARENT_OPERATION,
            client_flow_id=PARENT_FLOW,
        )

    async def catalog(self):
        return catalog()

    async def start_canary_recovery(self, request):
        assert self.events == ["prepare"]
        self.events.append("companion-start")
        self.recovery_request = request
        self.started = True
        return StartReceipt(accepted=True, code="accepted", operation_id=CHILD_OPERATION)

    async def finalize(self, operation_id):
        assert operation_id == CHILD_OPERATION
        self.events.append("finalize")
        self.finalized = True
        return FinalizeReceipt(released=True, code="flow_released")

    async def observe_membership(self, workspace_id):
        assert self.finalized
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id=workspace_id,
            workspace_account_id=WORKSPACE_ACCOUNT,
            catalog_fingerprint=FINGERPRINT,
            observed_at=NOW,
            complete=True,
            owner_verified=True,
            identity_ambiguous=False,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=[
                MembershipObservationMember(
                    email="original@example.com",
                    user_id="user-Original",
                    preset_id="original",
                    classification="allowlisted",
                )
            ],
        )


def test_exact_parent_and_completed_recovery_predicates_are_inverse_and_fail_closed():
    current = state()
    assert _exact_partial_parent(parent_operation(), current) is True
    assert _exact_completed_recovery(recovery_operation(), current) is True
    assert _exact_partial_parent(parent_operation().model_copy(update={"code": "other"}), current) is False
    assert _exact_completed_recovery(
        recovery_operation().model_copy(update={"target_user_id": "user-Other"}), current
    ) is False


async def test_partial_recovery_preflight_is_read_only_and_requires_exact_retained_parent():
    controls = Controls()
    events: list[str] = []
    companion = Companion(events)
    result = await run_recovery(
        execute=False,
        companion=companion,  # type: ignore[arg-type]
        controls=controls,  # type: ignore[arg-type]
        journal=Journal(),  # type: ignore[arg-type]
        service=Service(controls, events),  # type: ignore[arg-type]
        bindings=Bindings(),  # type: ignore[arg-type]
        accounts=Accounts(),  # type: ignore[arg-type]
        workspace_id="cdp-2",
        restore_preset_id="original",
        failed_target_preset_id="target",
    )
    assert result["ready"] is True
    assert result["parentRetained"] is True
    assert events == []

    with pytest.raises(RuntimeError, match="companion_parent_not_eligible"):
        await run_recovery(
            execute=False,
            companion=Companion([], bad_parent=True),  # type: ignore[arg-type]
            controls=Controls(),  # type: ignore[arg-type]
            journal=Journal(),  # type: ignore[arg-type]
            service=Service(Controls(), []),  # type: ignore[arg-type]
            bindings=Bindings(),  # type: ignore[arg-type]
            accounts=Accounts(),  # type: ignore[arg-type]
            workspace_id="cdp-2",
            restore_preset_id="original",
            failed_target_preset_id="target",
        )


async def test_partial_recovery_prepares_before_start_and_releases_controller_only_after_restoration(monkeypatch):
    controls = Controls()
    events: list[str] = []
    companion = Companion(events)
    service = Service(controls, events)
    monkeypatch.setattr(
        "app.modules.workspace_member_controller.legacy_partial_recovery_runner.uuid4",
        lambda: UUID(CHILD_FLOW),
    )

    result = await run_recovery(
        execute=True,
        companion=companion,  # type: ignore[arg-type]
        controls=controls,  # type: ignore[arg-type]
        journal=Journal(),  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        bindings=Bindings(),  # type: ignore[arg-type]
        accounts=Accounts(),  # type: ignore[arg-type]
        workspace_id="cdp-2",
        restore_preset_id="original",
        failed_target_preset_id="target",
    )

    assert result["completed"] is True
    assert events == ["prepare", "companion-start", "finalize", "controller-complete"]
    assert controls.record is None
    assert companion.recovery_request.client_flow_id == CHILD_FLOW
    assert companion.recovery_request.parent_client_flow_id == PARENT_FLOW
    assert companion.recovery_request.restore_preset_id == "original"
    assert companion.recovery_request.failed_target_preset_id == "target"


async def test_prepared_recovery_without_server_receipt_never_replays_start_effect():
    controls = Controls()
    events: list[str] = []
    companion = Companion(events)

    with pytest.raises(RuntimeError, match="partial_recovery_prepared_start_not_observed"):
        await run_recovery(
            execute=True,
            companion=companion,  # type: ignore[arg-type]
            controls=controls,  # type: ignore[arg-type]
            journal=Journal(prepared=True),  # type: ignore[arg-type]
            service=Service(controls, events),  # type: ignore[arg-type]
            bindings=Bindings(),  # type: ignore[arg-type]
            accounts=Accounts(),  # type: ignore[arg-type]
            workspace_id="cdp-2",
            restore_preset_id="original",
            failed_target_preset_id="target",
        )

    assert events == []
    assert companion.started is False


async def test_finalized_recovery_resumes_only_controller_completion_without_membership_replay():
    controls = Controls()
    events: list[str] = []
    companion = Companion(events, child_exists=True, finalized=True)

    result = await run_recovery(
        execute=True,
        companion=companion,  # type: ignore[arg-type]
        controls=controls,  # type: ignore[arg-type]
        journal=Journal(prepared=True),  # type: ignore[arg-type]
        service=Service(controls, events),  # type: ignore[arg-type]
        bindings=Bindings(),  # type: ignore[arg-type]
        accounts=Accounts(),  # type: ignore[arg-type]
        workspace_id="cdp-2",
        restore_preset_id="original",
        failed_target_preset_id="target",
    )

    assert result["completed"] is True
    assert events == ["controller-complete"]
    assert controls.record is None
    assert companion.recovery_request is None
