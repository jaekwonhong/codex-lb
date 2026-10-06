from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.modules.member_switch.schemas import (
    Catalog,
    FinalizeReceipt,
    InvitationSettlement,
    Member,
    Operation,
    OperationTraceEntry,
    Preview,
    StartReceipt,
    Workspace,
)
from app.modules.workspace_member_controller.legacy_companion_canary_effect import (
    LegacyCompanionCanarySwitchEffect,
)
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationCommand,
    MembershipMutationSpec,
    MembershipSubject,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)


def command() -> MembershipMutationCommand:
    return MembershipMutationCommand(
        operation_id=UUID("11111111-1111-4111-8111-111111111111"),
        command_id=UUID("22222222-2222-4222-8222-222222222222"),
        expected_revision=0,
        mutation=MembershipMutationSpec(
            action="switch",
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="a" * 64,
            incoming=MembershipSubject(preset_id="incoming", email="incoming@example.com", user_id="user-Incoming"),
            outgoing=MembershipSubject(preset_id="outgoing", email="outgoing@example.com", user_id="user-Outgoing"),
        ),
    )


def catalog() -> Catalog:
    return Catalog(
        enabled=True,
        schema_version=1,
        catalog_fingerprint="a" * 64,
        capabilities=[
            "ego_lite_device_auth_automation_v1",
            "ego_lite_owner_membership_observation_v1",
            "ego_lite_owner_membership_mutation_v1",
            "ego_lite_recipient_membership_lifecycle_v1",
            "member_rotation_canary_effect_gate_v1",
            "member_rotation_managed_remove_telemetry_v1",
            "durable_client_flow",
            "durable_participant_commands_v1",
        ],
        workspaces=[
            Workspace(
                id="workspace-1",
                workspace_account_id="workspace-account-1",
                workspace_name="Workspace",
                owner_email="owner@example.com",
                members=[
                    Member(
                        preset_id="incoming",
                        display_name="Incoming",
                        email="incoming@example.com",
                        user_id="user-Incoming",
                    ),
                    Member(
                        preset_id="outgoing",
                        display_name="Outgoing",
                        email="outgoing@example.com",
                        user_id="user-Outgoing",
                    ),
                ],
            )
        ],
    )


def completed_operation() -> Operation:
    return Operation(
        operation_id="effect-1",
        member_switch_operation_id="effect-1",
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        target_email="incoming@example.com",
        target_user_id="user-Incoming",
        stage="completed",
        code="member_added",
        removed_email="outgoing@example.com",
        removed_user_id="user-Outgoing",
        membership_state="active",
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
            automatic_observation_attempts=1,
            automatic_settlement_confirmed=True,
            pending_invitation_id=None,
            fallback_used=False,
            final_membership_confirmed=True,
            invitation_attempted=True,
        ),
    )


class Companion:
    def __init__(self):
        self.start_calls = 0
        self.finalize_calls = 0
        self.operation_value = completed_operation()

    async def catalog(self):
        return catalog()

    async def admission(self):
        from app.modules.member_switch.schemas import CompanionAdmission

        return CompanionAdmission(can_start=True, code="idle")

    async def preview(self, _request):
        return Preview(
            ready=True,
            code="ready",
            preview_token="preview-1",
            expires_at=NOW + timedelta(seconds=60),
            workspace_name="Workspace",
            owner_email="owner@example.com",
            target_email="incoming@example.com",
            remove_email="outgoing@example.com",
            catalog_fingerprint="a" * 64,
        )

    async def start(self, request):
        self.start_calls += 1
        assert request.canary is True
        return StartReceipt(accepted=True, code="accepted", operation_id="effect-1")

    async def lookup(self, _client_flow_id):
        return StartReceipt(accepted=True, code="accepted", operation_id="effect-1")

    async def operation(self, _operation_id):
        return self.operation_value

    async def finalize(self, _operation_id):
        self.finalize_calls += 1
        return FinalizeReceipt(released=True, code="released")


async def test_canary_switch_requires_qualified_evidence_and_finalizes_once():
    companion = Companion()
    effect = LegacyCompanionCanarySwitchEffect(companion, clock=lambda: NOW, settle_timeout_seconds=0)
    result = await effect.execute(command())
    assert result.outcome == "completed"
    assert result.remove_effect == "confirmed"
    assert result.add_effect == "confirmed"
    assert result.final_membership_confirmed is True
    assert companion.start_calls == 1
    assert companion.finalize_calls == 1


async def test_reconcile_never_resends_canary_start():
    companion = Companion()
    effect = LegacyCompanionCanarySwitchEffect(companion, clock=lambda: NOW, settle_timeout_seconds=0)
    cmd = command()
    result = await effect.reconcile(
        operation_id=str(cmd.operation_id),
        command_id=str(cmd.command_id),
        request_fingerprint=cmd.fingerprint(),
        mutation=cmd.mutation,
    )
    assert result is not None and result.outcome == "completed"
    assert companion.start_calls == 0
    assert companion.finalize_calls == 1


async def test_missing_removal_trace_remains_outcome_unknown_and_is_not_finalized():
    companion = Companion()
    companion.operation_value = completed_operation().model_copy(update={"trace": []})
    effect = LegacyCompanionCanarySwitchEffect(companion, clock=lambda: NOW, settle_timeout_seconds=0)
    result = await effect.execute(command())
    assert result.outcome == "outcome_unknown"
    assert companion.start_calls == 1
    assert companion.finalize_calls == 0
