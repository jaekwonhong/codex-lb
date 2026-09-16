from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.usage.weekly_observation import (
    ClassifiedUsageWindowObservation,
    RotationUsageObservation,
    UsageAccountIdentity,
    UsageFetchProvenance,
)
from app.db.models import (
    Account,
    MemberRotationQuotaOperation,
    MemberSwitchCommandReceipt,
    MemberSwitchControlRecord,
    WorkspaceMemberFinalUsageSnapshot,
    WorkspaceMemberUsageResetInvalidation,
)
from app.modules.member_auth_handoff.rotation_events import RotationQuotaDecision, RotationQuotaRepository
from app.modules.member_switch import schemas as member_switch_schemas
from app.modules.member_switch.companion import CompanionPort
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.rotation_controller import (
    RotationController,
    rotation_controller_id,
    rotation_run_id,
    select_rotation_candidate,
)
from app.modules.member_switch.rotation_foundation import (
    RotationEvaluationIdentity,
    RotationQuotaReservationEvidence,
    RotationResetEvidence,
    bind_rotation_reset_resolution,
    bind_rotation_weekly_evidence,
    reserve_rotation_quota,
)
from app.modules.member_switch.schemas import (
    P4_TYPED_TELEMETRY_BINARY_SHA256,
    P4_TYPED_TELEMETRY_CONTRACT,
    P4_TYPED_TELEMETRY_OPS_COMMIT,
    P4_TYPED_TELEMETRY_VERSION,
    Catalog,
    CommandRequest,
    CompanionAdmission,
    CompanionTypedTelemetryProvenance,
    CreateRunRequest,
    CurrentMember,
    FinalizeReceipt,
    Member,
    MemberMutationResponseObservation,
    MemberRemovalObservationResponse,
    MembershipObservation,
    MembershipObservationMember,
    Operation,
    OwnerAuthTarget,
    Preview,
    StartReceipt,
    Workspace,
)
from app.modules.member_switch.service import AuthHandoffPort, MemberSwitchService
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditResolution,
    RotationResetCreditResolutionStatus,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
WORKSPACE_ID = "workspace-1"
WORKSPACE_ACCOUNT_ID = "workspace-account-1"
OUTGOING = UsageAccountIdentity(
    account_id="account-current",
    workspace_account_id=WORKSPACE_ACCOUNT_ID,
    user_id="user-Current",
    email="current@example.com",
)


@dataclass
class MutableClock:
    current: datetime = NOW

    def __call__(self) -> datetime:
        return self.current


class RotationFakeAuth:
    def bind_catalog(self, catalog) -> None:
        self.catalog = catalog

    def validate_identity(self, identity, removed_email=None) -> None:
        if identity.catalog_fingerprint != "a" * 64:
            raise ControlConflict("auth_catalog_identity_mismatch")

    async def observe_workspace_auth(self, *, workspace_id, workspace_account_id):
        raise RuntimeError("synthetic auth observation unavailable")


class RotationFakeCompanion:
    def __init__(self) -> None:
        self.start_calls = 0
        self.finalize_calls = 0
        self.lose_start_response = False
        self.lose_finalize_response = False
        self.lookup_available = True
        self.receipt: StartReceipt | None = None
        self.start_receipt = StartReceipt(accepted=True, code="accepted", operation_id="operation-1")
        self.operation_snapshot = self.removing_operation()
        self.admission_results: list[CompanionAdmission] = []

    @staticmethod
    def removing_operation() -> Operation:
        return Operation(
            operation_id="operation-1",
            member_switch_operation_id="operation-1",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            target_email="target@example.com",
            target_user_id="user-Target",
            stage="removing",
            code="removing",
            removed_email=None,
            removed_user_id=None,
            membership_state="unknown",
            updated_at=NOW,
        )

    def catalog_value(self) -> Catalog:
        return Catalog(
            enabled=True,
            schema_version=1,
            catalog_fingerprint="a" * 64,
            capabilities=[
                "recipient_acceptance",
                "recipient_session_readiness",
                "post_add_device_auth",
                "ego_lite_member_browser_v1",
                "ego_lite_device_auth_automation_v1",
                "ego_lite_owner_membership_observation_v1",
                "ego_lite_owner_membership_mutation_v1",
                "ego_lite_recipient_membership_lifecycle_v1",
                "durable_client_flow",
                "durable_participant_commands_v1",
                "managed_member_switch_v1",
            ],
            workspaces=[
                Workspace(
                    id=WORKSPACE_ID,
                    workspace_account_id=WORKSPACE_ACCOUNT_ID,
                    workspace_name="Synthetic",
                    owner_email="owner@example.com",
                    owner_auth=OwnerAuthTarget(
                        preset_id=f"owner:{WORKSPACE_ID}",
                        email="owner@example.com",
                        user_id="user-Owner",
                    ),
                    members=[
                        Member(
                            preset_id="current",
                            display_name="Current",
                            email=OUTGOING.email,
                            user_id=OUTGOING.user_id or "",
                        ),
                        Member(
                            preset_id="target",
                            display_name="Target",
                            email="target@example.com",
                            user_id="user-Target",
                        ),
                    ],
                )
            ],
        )

    async def admission(self) -> CompanionAdmission:
        if self.admission_results:
            return self.admission_results.pop(0)
        return CompanionAdmission(can_start=True, code="ready")

    async def catalog(self) -> Catalog:
        return self.catalog_value()

    async def observe_membership(self, workspace_id: str) -> MembershipObservation:
        assert workspace_id == WORKSPACE_ID
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            catalog_fingerprint="a" * 64,
            observed_at=NOW,
            complete=True,
            owner_verified=True,
            identity_ambiguous=False,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=[
                MembershipObservationMember(
                    email="owner@example.com",
                    user_id="user-Owner",
                    classification="owner",
                ),
                MembershipObservationMember(
                    email=OUTGOING.email,
                    user_id=OUTGOING.user_id or "",
                    classification="member",
                ),
            ],
        )

    async def preview(self, request) -> Preview:
        return Preview(
            ready=True,
            code="ready",
            preview_token="preview-1",
            expires_at=NOW + timedelta(days=30),
            workspace_name="Synthetic",
            owner_email="owner@example.com",
            target_email="target@example.com",
            remove_email=OUTGOING.email,
            catalog_fingerprint="a" * 64,
        )

    async def start(self, request) -> StartReceipt:
        self.start_calls += 1
        self.receipt = self.start_receipt
        if self.lose_start_response:
            raise ControlConflict("companion_outcome_unknown")
        return self.receipt

    async def lookup(self, client_flow_id: str) -> StartReceipt | None:
        return self.receipt if self.lookup_available else None

    async def operation(self, operation_id: str) -> Operation:
        assert operation_id == "operation-1"
        return self.operation_snapshot

    async def finalize(self, operation_id: str) -> FinalizeReceipt:
        self.finalize_calls += 1
        self.receipt = StartReceipt(accepted=True, code="operation_finalized", operation_id=operation_id)
        if self.lose_finalize_response:
            raise ControlConflict("companion_outcome_unknown")
        return FinalizeReceipt(released=True, code="released")


@pytest_asyncio.fixture
async def rotation_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rotation.sqlite'}")
    async with engine.begin() as connection:
        for table in (
            Account.__table__,
            MemberSwitchControlRecord.__table__,
            MemberSwitchCommandReceipt.__table__,
            MemberRotationQuotaOperation.__table__,
            WorkspaceMemberUsageResetInvalidation.__table__,
            WorkspaceMemberFinalUsageSnapshot.__table__,
        ):
            await connection.run_sync(cast(Table, table).create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = RotationFakeCompanion()
    switch = MemberSwitchService(controls, cast(CompanionPort, companion), cast(AuthHandoffPort, RotationFakeAuth()))
    clock = MutableClock()
    controller = RotationController(controls, switch, sessions, sessions, clock=clock)
    yield controller, switch, controls, companion, sessions, clock
    await engine.dispose()


def p4_provenance(**changes: str) -> CompanionTypedTelemetryProvenance:
    values = {
        "contract": P4_TYPED_TELEMETRY_CONTRACT,
        "version": P4_TYPED_TELEMETRY_VERSION,
        "binary_sha256": P4_TYPED_TELEMETRY_BINARY_SHA256,
        "ops_commit": P4_TYPED_TELEMETRY_OPS_COMMIT,
    }
    values.update(changes)
    return CompanionTypedTelemetryProvenance(**values)


def receipt(*, member: UsageAccountIdentity = OUTGOING, weekly_used: float = 100.0) -> RotationUsageObservation:
    return RotationUsageObservation(
        fetch_succeeded=True,
        usage_written=False,
        provenance=UsageFetchProvenance(
            fetch_id=str(uuid4()),
            identity=member,
            requested_workspace_account_id=member.workspace_account_id,
            account_workspace_id="usage-workspace",
            payload_workspace_id="usage-workspace",
            credential_source="stored",
            started_at=NOW - timedelta(seconds=1),
            observed_at=NOW,
        ),
        five_hour_window=ClassifiedUsageWindowObservation(
            source_slot="primary",
            raw_used_percent=45.0,
            window_minutes=300,
            limit_window_seconds=18_000,
            reset_at=int((NOW + timedelta(hours=2)).timestamp()),
        ),
        weekly_window=ClassifiedUsageWindowObservation(
            source_slot="secondary",
            raw_used_percent=weekly_used,
            window_minutes=10_080,
            limit_window_seconds=604_800,
            reset_at=int((NOW + timedelta(days=2)).timestamp()),
        ),
    )


def evidence(evaluation_id: str, *, weekly_used: float = 100.0):
    evaluation = RotationEvaluationIdentity(
        evaluation_id=evaluation_id,
        workspace_id=WORKSPACE_ID,
        member=OUTGOING,
        redeem_request_id=f"reset-{evaluation_id}",
    )
    weekly = bind_rotation_weekly_evidence(receipt(weekly_used=weekly_used), evaluation)
    reset = bind_rotation_reset_resolution(
        evaluation,
        RotationResetCreditResolution(
            status=RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT,
            redeem_request_id=evaluation.redeem_request_id,
            account_id=OUTGOING.account_id,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
        ),
    )
    return evaluation, weekly, reset


async def admitted_quota(
    sessions: async_sessionmaker[AsyncSession],
    clock: MutableClock,
    weekly,
    reset,
    *,
    operation_id: str,
) -> RotationQuotaReservationEvidence:
    async with sessions() as session:
        return await reserve_rotation_quota(
            RotationQuotaRepository(session, clock=clock),
            weekly=weekly,
            reset=reset,
            current_member=OUTGOING,
            now=clock(),
            operation_id=operation_id,
        )


def joined_operation(*, capture_state: str = "json") -> Operation:
    return Operation.model_validate(
        {
            "operationId": "operation-1",
            "memberSwitchOperationId": "operation-1",
            "workspaceId": WORKSPACE_ID,
            "workspaceAccountId": WORKSPACE_ACCOUNT_ID,
            "targetEmail": "target@example.com",
            "targetUserId": "user-Target",
            "stage": "completed",
            "code": "member_added",
            "removedEmail": OUTGOING.email,
            "removedUserId": OUTGOING.user_id,
            "membershipState": "active",
            "updatedAt": NOW,
            "invitationSettlement": {
                "invitationIssued": True,
                "automaticObservationAttempts": 2,
                "automaticSettlementConfirmed": True,
                "pendingInvitationId": "invite-1",
                "fallbackUsed": False,
                "finalMembershipConfirmed": True,
                "invitationAttempted": True,
                "recipientWorkspaceRefreshAttempts": 2,
                "recipientWorkspaceObserved": True,
                "inviteResponseObservation": {
                    "event": "invite_response",
                    "captureState": capture_state,
                    "httpStatus": 200,
                    "fields": {"seat_count": 5, "ok": True, "notice": None},
                },
                "invitationNonEffectConfirmed": False,
            },
        }
    )


def invite_non_effect_operation() -> Operation:
    operation = joined_operation()
    settlement = operation.invitation_settlement
    assert settlement is not None
    return operation.model_copy(
        update={
            "stage": "needs_attention",
            "code": "invite_rejected",
            "membership_state": "unknown",
            "invitation_settlement": settlement.model_copy(
                update={
                    "invitation_issued": False,
                    "automatic_settlement_confirmed": False,
                    "final_membership_confirmed": False,
                    "invitation_non_effect_confirmed": True,
                }
            ),
        }
    )


def test_typed_telemetry_preserves_primitives_null_and_absence() -> None:
    observation = MemberMutationResponseObservation.model_validate(
        {
            "event": "invite_response",
            "captureState": "json",
            "httpStatus": 200,
            "fields": {"number": 7, "boolean": True, "string": "seven", "null": None},
        }
    )
    assert type(observation.fields["number"]) is int
    assert type(observation.fields["boolean"]) is bool
    assert observation.fields["string"] == "seven"
    assert "null" in observation.fields and observation.fields["null"] is None
    assert "absent" not in observation.fields
    for capture_state in (
        "empty_body",
        "json_parse_failure",
        "response_not_received",
        "transport_failure",
        "body_read_failure",
        "sanitization_failure",
        "capture_failure",
    ):
        assert (
            MemberMutationResponseObservation(
                event="remove_response",
                capture_state=capture_state,
                fields={},
            ).capture_state
            == capture_state
        )


def test_p4_remove_observation_wire_contract_preserves_typed_response() -> None:
    response = MemberRemovalObservationResponse.model_validate(
        {
            "accepted": True,
            "code": "removal_observation_confirmed",
            "observationId": "observation-1",
            "mutationSent": True,
            "outcomeUnknown": False,
            "immediateResponseOk": True,
            "httpStatus": 200,
            "removalConfirmed": True,
            "stableObservations": 2,
            "responseObservation": {
                "event": "remove_response",
                "captureState": "json",
                "httpStatus": 200,
                "fields": {"quota.limit": 5, "policy.eligible": True, "policy.maximum": None},
            },
        }
    )
    assert response.accepted
    assert response.removal_confirmed
    assert response.stable_observations == 2
    assert response.response_observation is not None
    assert type(response.response_observation.fields["quota.limit"]) is int
    assert type(response.response_observation.fields["policy.eligible"]) is bool
    assert "policy.maximum" in response.response_observation.fields
    assert response.response_observation.fields["policy.maximum"] is None


def test_candidate_selection_uses_member_allowlist_and_excludes_owner_and_current() -> None:
    workspace = (
        RotationFakeCompanion()
        .catalog_value()
        .workspaces[0]
        .model_copy(
            update={
                "membership_observed_at": NOW,
                "current_members": [
                    CurrentMember(email=OUTGOING.email, user_id=OUTGOING.user_id or "", preset_id="current")
                ],
            }
        )
    )
    outgoing_preset, candidate = select_rotation_candidate(workspace, outgoing=OUTGOING)
    assert outgoing_preset == "current"
    assert candidate.preset_id == "target"
    assert candidate.email != workspace.owner_email
    assert workspace.owner_auth is not None and workspace.owner_auth.preset_id != candidate.preset_id


@pytest.mark.parametrize(
    ("status", "attention"),
    [
        (RotationResetCreditResolutionStatus.RECONCILIATION_PENDING, True),
        (RotationResetCreditResolutionStatus.USAGE_RECOVERED, False),
    ],
)
async def test_foundation_non_admission_never_creates_effect_run(rotation_context, status, attention) -> None:
    controller, _, controls, companion, _, _ = rotation_context
    evaluation, weekly, _ = evidence(f"foundation-{status.value}")
    reset = RotationResetEvidence(
        evaluation=evaluation,
        resolution=RotationResetCreditResolution(
            status=status,
            redeem_request_id=evaluation.redeem_request_id,
            account_id=OUTGOING.account_id,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
        ),
    )
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=None,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch=f"epoch-{status.value}",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == ("needs_attention" if attention else "completed")
    assert companion.start_calls == 0
    assert await controls.get(state.member_switch_run_id) is None


async def test_quota_blocked_and_invalid_evidence_never_create_effect_run(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    evaluation, weekly, reset = evidence("blocked")
    blocked = RotationQuotaReservationEvidence(
        evaluation=evaluation,
        operation_id="blocked-quota",
        decision=RotationQuotaDecision(
            admitted=False,
            code="rolling_24h_limit",
            count_24h=3,
            count_168h=3,
        ),
    )
    blocked_state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=blocked,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-blocked",
        p4_provenance=p4_provenance(),
    )
    assert blocked_state.foundation_state == "quota_blocked"
    assert companion.start_calls == 0

    _, foreign_weekly, foreign_reset = evidence("foreign")
    foreign_reservation = await admitted_quota(
        sessions,
        clock,
        foreign_weekly,
        foreign_reset,
        operation_id="foreign-quota",
    )
    _, invalid_weekly, invalid_reset = evidence("invalid")
    foreign = RotationQuotaReservationEvidence(
        evaluation=foreign_reservation.evaluation,
        operation_id=foreign_reservation.operation_id,
        decision=foreign_reservation.decision,
    )
    invalid_state = await controller.evaluate_and_start(
        weekly=invalid_weekly,
        reset=invalid_reset,
        quota=foreign,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-invalid",
        p4_provenance=p4_provenance(),
    )
    assert invalid_state.foundation_state == "invalid_evidence"
    assert invalid_state.quota_operation_id is None
    assert await controls.get(invalid_state.member_switch_run_id) is None
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, foreign_reservation.operation_id)
        assert row is not None and row.reservation_released_at is None


async def test_missing_or_wrong_p4_provenance_fails_closed_and_releases_quota(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    for suffix, provenance in (
        ("missing", None),
        ("wrong", p4_provenance(version="2.11.46")),
    ):
        _, weekly, reset = evidence(f"p4-{suffix}")
        quota = await admitted_quota(sessions, clock, weekly, reset, operation_id=f"quota-p4-{suffix}")
        state = await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch=f"epoch-p4-{suffix}",
            p4_provenance=provenance,
        )
        assert state.phase == "needs_attention"
        assert state.last_code == "rotation_p4_provenance_unverified"
        assert await controls.get(state.member_switch_run_id) is None
        async with sessions() as session:
            row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
            assert row is not None and row.reservation_released_at is not None
    assert companion.start_calls == 0


async def test_snapshot_failure_or_identity_mismatch_blocks_start(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("snapshot-failure")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-snapshot-failure")
    bad_member = replace(OUTGOING, account_id="different-account")
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(member=bad_member),
        membership_epoch="epoch-snapshot-failure",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert state.last_code == "usage_unknown"
    assert companion.start_calls == 0
    assert await controls.get(state.member_switch_run_id) is None


async def test_lost_start_response_restart_reconciles_without_replay(rotation_context) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("lost-start")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-lost-start")
    companion.lose_start_response = True
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-lost-start",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "removal_effect_unknown"
    assert companion.start_calls == 1

    companion.lose_start_response = False
    restarted = RotationController(controls, switch, sessions, sessions, clock=clock)
    state = await restarted.resume(state.id)
    assert companion.start_calls == 1
    assert state.remove_state == "unknown"
    assert state.phase == "removal_effect_unknown"

    # A second scheduler tick is read-only reconciliation as well.
    await restarted.resume(state.id)
    assert companion.start_calls == 1


async def test_restart_after_child_creation_resumes_same_durable_start_claim(rotation_context, monkeypatch) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("child-created-crash")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-child-created-crash")

    async def crash_after_child_claim_before_controller_accounting(operation_id: str, effect: str) -> None:
        assert operation_id == quota.operation_id
        assert effect == "remove"
        raise RuntimeError("synthetic process crash")

    monkeypatch.setattr(controller, "_quota_request", crash_after_child_claim_before_controller_accounting)
    with pytest.raises(RuntimeError, match="synthetic process crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-child-created-crash",
            p4_provenance=p4_provenance(),
        )
    assert companion.start_calls == 0

    controller_id = rotation_controller_id("child-created-crash")
    before_restart = await controller.get(controller_id)
    assert before_restart is not None
    assert before_restart.snapshot_committed
    assert before_restart.remove_state == "not_attempted"
    child = await switch.get(before_restart.member_switch_run_id)
    assert child is not None and child.pending_action == "start"

    restarted = RotationController(controls, switch, sessions, sessions, clock=clock)
    resumed = await restarted.resume(controller_id)
    assert companion.start_calls == 0
    assert resumed.remove_state == "unknown"
    assert resumed.phase == "removal_effect_unknown"


async def test_companion_restart_with_missing_receipt_never_replays_start(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("companion-restart")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-companion-restart")
    companion.lose_start_response = True
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-companion-restart",
        p4_provenance=p4_provenance(),
    )
    assert companion.start_calls == 1

    restarted_companion = RotationFakeCompanion()
    restarted_companion.lookup_available = False
    restarted_switch = MemberSwitchService(
        controls, cast(CompanionPort, restarted_companion), cast(AuthHandoffPort, RotationFakeAuth())
    )
    restarted_controller = RotationController(controls, restarted_switch, sessions, sessions, clock=clock)
    resumed = await restarted_controller.resume(state.id)
    assert resumed.phase == "removal_effect_unknown"
    assert restarted_companion.start_calls == 0


async def test_concurrent_resume_workers_never_replay_start(rotation_context) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("concurrent-resume")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-concurrent-resume")
    companion.lose_start_response = True
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-concurrent-resume",
        p4_provenance=p4_provenance(),
    )
    assert companion.start_calls == 1
    companion.lose_start_response = False

    worker_a = RotationController(controls, switch, sessions, sessions, clock=clock)
    worker_b = RotationController(controls, switch, sessions, sessions, clock=clock)
    first, second = await asyncio.gather(worker_a.resume(state.id), worker_b.resume(state.id))

    assert companion.start_calls == 1
    assert first.remove_state == "unknown"
    assert second.remove_state == "unknown"
    assert (await controller.get(state.id)).phase == "removal_effect_unknown"  # type: ignore[union-attr]


async def test_invite_parse_failure_enters_attention_without_second_operation_start(rotation_context) -> None:
    controller, _, _, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("invite-parse")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-invite-parse")
    companion.operation_snapshot = joined_operation(capture_state="json_parse_failure").model_copy(
        update={"stage": "needs_attention", "membership_state": "unknown"}
    )
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-invite-parse",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert state.invite_state == "confirmed"
    assert state.invite_response_observation is not None
    assert state.invite_response_observation.capture_state == "json_parse_failure"
    assert companion.start_calls == 1
    await controller.resume(state.id)
    assert companion.start_calls == 1


async def test_invite_sent_is_not_joined_and_quota_history_is_retained(rotation_context) -> None:
    controller, _, _, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("invite-not-joined")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-invite-not-joined")
    operation = joined_operation()
    settlement = operation.invitation_settlement
    assert settlement is not None
    companion.operation_snapshot = operation.model_copy(
        update={
            "stage": "waiting_membership",
            "code": "invitation_sent",
            "membership_state": "unknown",
            "invitation_settlement": settlement.model_copy(
                update={
                    "automatic_settlement_confirmed": False,
                    "final_membership_confirmed": False,
                    "recipient_workspace_observed": False,
                }
            ),
        }
    )
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-invite-not-joined",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "waiting_membership"
    assert state.remove_state == "confirmed"
    assert state.invite_state == "confirmed"
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None and row.completed_at is None and row.reservation_released_at is None


async def test_remove_confirmed_invite_non_effect_keeps_history(rotation_context) -> None:
    controller, _, _, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("invite-non-effect")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-invite-non-effect")
    companion.operation_snapshot = invite_non_effect_operation()
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-invite-non-effect",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert state.remove_state == "confirmed"
    assert state.invite_state == "authoritative_non_effect"
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None
        assert row.remove_effect == "confirmed"
        assert row.invite_effect == "authoritative_non_effect"
        assert row.reservation_released_at is None


async def test_terminal_membership_marks_quota_and_releases_automatic_run(rotation_context) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("complete")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-complete")
    companion.operation_snapshot = joined_operation()
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-complete",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "completed"
    assert companion.start_calls == 1
    assert companion.finalize_calls == 1
    assert await controls.active() is None
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None and row.completed_at is not None
        snapshots = (
            await session.scalars(
                select(WorkspaceMemberFinalUsageSnapshot).where(
                    WorkspaceMemberFinalUsageSnapshot.membership_epoch == "epoch-complete"
                )
            )
        ).all()
        assert len(snapshots) == 2

    run = await switch.get(state.member_switch_run_id)
    assert run is not None and run.phase == "completed"


async def test_public_manual_command_cannot_drive_automatic_run(rotation_context) -> None:
    controller, switch, _, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("manual-race")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-manual-race")
    companion.operation_snapshot = RotationFakeCompanion.removing_operation()
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-manual-race",
        p4_provenance=p4_provenance(),
    )
    run = await switch.get(state.member_switch_run_id)
    assert run is not None
    with pytest.raises(ControlConflict, match="rotation_run_owned"):
        await switch.command(
            run.id,
            CommandRequest(command_id=uuid4(), expected_revision=run.revision, action="observe_membership"),
        )


async def test_manual_active_run_blocks_automatic_before_effect(rotation_context) -> None:
    controller, switch, _, companion, sessions, clock = rotation_context
    manual = await switch.create(
        # Same allowed catalog target; the manual run owns the global effect scope.
        CreateRunRequest(
            run_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            preset_id="target",
            catalog_fingerprint="a" * 64,
        )
    )
    assert manual.phase == "previewed"
    _, weekly, reset = evidence("manual-active")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-manual-active")
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-manual-active",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert state.last_code.startswith("rotation_member_switch_blocked:")
    assert companion.start_calls == 0


async def test_snapshot_epoch_is_reused_on_restart_without_overwrite(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("snapshot-restart")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-snapshot-restart")

    # Simulate a crash after P3 committed the exact epoch but before the controller
    # could durably publish snapshot_committed by pre-populating the immutable P3 rows.
    final_receipt = receipt()
    from app.modules.member_auth_handoff.usage_snapshot_repository import MemberUsageSnapshotRepository
    from app.modules.member_switch.rotation_foundation import final_usage_snapshot_inputs

    inputs = final_usage_snapshot_inputs(final_receipt, weekly.evaluation, OUTGOING, now=clock())
    async with sessions() as session:
        first = await MemberUsageSnapshotRepository(session, clock=clock).retain_final_snapshots(
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_id=OUTGOING.account_id,
            preset_id="current",
            email=OUTGOING.email,
            user_id=OUTGOING.user_id or "",
            membership_epoch="epoch-snapshot-restart",
            observations=inputs,
        )
    assert len(first) == 2

    companion.operation_snapshot = RotationFakeCompanion.removing_operation()
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=final_receipt,
        membership_epoch="epoch-snapshot-restart",
        p4_provenance=p4_provenance(),
    )
    assert state.snapshot_committed
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(WorkspaceMemberFinalUsageSnapshot).where(
                    WorkspaceMemberFinalUsageSnapshot.membership_epoch == "epoch-snapshot-restart"
                )
            )
        ).all()
        assert len(rows) == 2
    assert await controls.get(rotation_controller_id("snapshot-restart")) is not None


async def test_unclaimed_preview_requires_fresh_foundation_after_restart(rotation_context, monkeypatch) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("fresh-boundary")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-fresh-boundary")

    async def crash_before_start(record, state, run):
        raise RuntimeError("synthetic pre-start crash")

    monkeypatch.setattr(controller, "_start_child", crash_before_start)
    with pytest.raises(RuntimeError, match="synthetic pre-start crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-fresh-boundary",
            p4_provenance=p4_provenance(),
        )
    assert companion.start_calls == 0
    controller_id = rotation_controller_id("fresh-boundary")
    child = await controls.get(rotation_run_id("fresh-boundary"))
    assert child is not None and child.pending_action is None

    restarted = RotationController(controls, controller.member_switch, sessions, sessions, clock=clock)
    resumed = await restarted.resume(controller_id)
    assert resumed.phase == "foundation_evaluating"
    assert companion.start_calls == 0

    clock.current = NOW + timedelta(days=3)
    stale = await restarted.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=None,
        membership_epoch="epoch-fresh-boundary",
        p4_provenance=p4_provenance(),
    )
    assert stale.foundation_state == "usage_unknown"
    assert stale.phase == "needs_attention"
    assert companion.start_calls == 0


async def test_unclaimed_preview_requalifies_p4_before_start(rotation_context, monkeypatch) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("p4-requalify")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-p4-requalify")

    async def crash_before_start(record, state, run):
        raise RuntimeError("synthetic pre-start crash")

    monkeypatch.setattr(controller, "_start_child", crash_before_start)
    with pytest.raises(RuntimeError, match="synthetic pre-start crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-p4-requalify",
            p4_provenance=p4_provenance(),
        )
    assert companion.start_calls == 0

    monkeypatch.setattr(member_switch_schemas, "P4_TYPED_TELEMETRY_VERSION", "2.11.48")
    restarted = RotationController(controls, controller.member_switch, sessions, sessions, clock=clock)
    stored = await restarted.get(rotation_controller_id("p4-requalify"))
    assert stored is not None and not stored.p4_provenance_verified
    state = await restarted.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-p4-requalify",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert state.last_code == "rotation_p4_provenance_unverified"
    assert companion.start_calls == 0


async def test_committed_snapshot_without_child_is_reused_after_fresh_evaluation(rotation_context, monkeypatch) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("snapshot-child-gap")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-snapshot-child-gap")
    original_create = switch.create_rotation_run

    async def crash_before_child_create(*args, **kwargs):
        raise RuntimeError("synthetic child-create crash")

    monkeypatch.setattr(switch, "create_rotation_run", crash_before_child_create)
    with pytest.raises(RuntimeError, match="synthetic child-create crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-snapshot-child-gap",
            p4_provenance=p4_provenance(),
        )
    controller_id = rotation_controller_id("snapshot-child-gap")
    before = await controller.get(controller_id)
    assert before is not None and before.snapshot_committed and len(before.final_snapshot_ids) == 2
    original_ids = list(before.final_snapshot_ids)
    assert await controls.get(before.member_switch_run_id) is None

    monkeypatch.setattr(switch, "create_rotation_run", original_create)
    restarted = RotationController(controls, switch, sessions, sessions, clock=clock)
    resumed = await restarted.resume(controller_id)
    assert resumed.last_code == "rotation_fresh_evaluation_required"
    assert companion.start_calls == 0

    state = await restarted.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=None,
        membership_epoch="epoch-snapshot-child-gap",
        p4_provenance=p4_provenance(),
    )
    assert companion.start_calls == 1
    assert state.final_snapshot_ids == original_ids
    async with sessions() as session:
        snapshots = (
            await session.scalars(
                select(WorkspaceMemberFinalUsageSnapshot).where(
                    WorkspaceMemberFinalUsageSnapshot.membership_epoch == "epoch-snapshot-child-gap"
                )
            )
        ).all()
        assert len(snapshots) == 2


async def test_start_rejection_is_authoritative_non_effect_and_releases_scope(rotation_context) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("start-non-effect")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-start-non-effect")
    companion.start_receipt = StartReceipt(accepted=False, code="preview_expired", operation_id=None)

    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-start-non-effect",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "completed"
    assert state.remove_state == "authoritative_non_effect"
    assert companion.start_calls == 1
    assert await controls.active() is None
    run = await switch.get(state.member_switch_run_id)
    assert run is not None and run.phase == "completed"
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None
        assert row.remove_effect == "authoritative_non_effect"
        assert row.reservation_released_at is not None
        assert row.completed_at is None


async def test_crash_after_quota_completion_recovers_from_terminal_quota(rotation_context, monkeypatch) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("quota-completion-crash")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-completion-crash")
    companion.operation_snapshot = joined_operation()
    original_complete = controller._complete_quota

    async def complete_then_crash(operation_id: str) -> None:
        await original_complete(operation_id)
        raise RuntimeError("synthetic post-quota crash")

    monkeypatch.setattr(controller, "_complete_quota", complete_then_crash)
    with pytest.raises(RuntimeError, match="synthetic post-quota crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-quota-completion-crash",
            p4_provenance=p4_provenance(),
        )
    assert companion.finalize_calls == 1
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None and row.completed_at is not None

    restarted = RotationController(controls, switch, sessions, sessions, clock=clock)
    state = await restarted.resume(rotation_controller_id("quota-completion-crash"))
    assert state.phase == "completed"
    assert state.remove_state == "confirmed"
    assert state.invite_state == "confirmed"
    assert companion.start_calls == 1


async def test_pending_finish_reconciles_after_restart_without_second_finalize(rotation_context) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("finish-reconcile")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-finish-reconcile")
    companion.operation_snapshot = joined_operation()
    companion.lose_finalize_response = True

    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-finish-reconcile",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "finalizing"
    assert companion.finalize_calls == 1
    run = await switch.get(state.member_switch_run_id)
    assert run is not None and run.pending_action == "finish"

    companion.lose_finalize_response = False
    restarted = RotationController(controls, switch, sessions, sessions, clock=clock)
    state = await restarted.resume(state.id)
    assert state.phase == "completed"
    assert companion.finalize_calls == 1
    assert await controls.active() is None


async def test_final_usage_receipt_reassesses_weekly_before_remove(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("final-usage-recovers")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-final-usage-recovers")

    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(weekly_used=10.0),
        membership_epoch="epoch-final-usage-recovers",
        p4_provenance=p4_provenance(),
    )
    assert state.foundation_state == "usage_available"
    assert state.phase == "completed"
    assert companion.start_calls == 0
    assert await controls.get(state.member_switch_run_id) is None
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None and row.reservation_released_at is not None


async def test_fresh_re_evaluation_starts_existing_unclaimed_preview(rotation_context, monkeypatch) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("owned-preview")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-owned-preview")

    async def crash_before_start(record, state, run):
        raise RuntimeError("synthetic pre-start crash")

    original_start_child = controller._start_child
    monkeypatch.setattr(controller, "_start_child", crash_before_start)
    with pytest.raises(RuntimeError, match="synthetic pre-start crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-owned-preview",
            p4_provenance=p4_provenance(),
        )
    assert companion.start_calls == 0
    controller_id = rotation_controller_id("owned-preview")
    resumed = await controller.resume(controller_id)
    assert resumed.phase == "foundation_evaluating"

    monkeypatch.setattr(controller, "_start_child", original_start_child)
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=None,
        membership_epoch="epoch-owned-preview",
        p4_provenance=p4_provenance(),
    )
    assert state.remove_state == "unknown"
    assert companion.start_calls == 1
    child = await controls.get(state.member_switch_run_id)
    assert child is not None and child.active_scope is not None


async def test_released_quota_blocks_child_start_before_external_effect(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("released-before-start")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-released-before-start")
    async with sessions() as session:
        released = await RotationQuotaRepository(session, clock=clock).release_reservation(quota.operation_id)
        assert released

    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-released-before-start",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert state.last_code.startswith("rotation_remove_preflight_failed:")
    assert companion.start_calls == 0
    run = await controls.get(state.member_switch_run_id)
    assert run is not None and run.active_scope is None


async def test_snapshot_commit_before_parent_publication_recovers_existing_epoch(rotation_context, monkeypatch) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("snapshot-publish-gap")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-snapshot-publish-gap")
    original_persist = controller._persist

    async def crash_before_snapshot_publication(record, state):
        if state.snapshot_committed and state.final_snapshot_ids:
            raise RuntimeError("synthetic snapshot publication crash")
        return await original_persist(record, state)

    monkeypatch.setattr(controller, "_persist", crash_before_snapshot_publication)
    with pytest.raises(RuntimeError, match="synthetic snapshot publication crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-snapshot-publish-gap",
            p4_provenance=p4_provenance(),
        )
    assert companion.start_calls == 0
    controller_id = rotation_controller_id("snapshot-publish-gap")
    stored = await controller.get(controller_id)
    assert stored is not None and not stored.snapshot_committed
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(WorkspaceMemberFinalUsageSnapshot).where(
                    WorkspaceMemberFinalUsageSnapshot.membership_epoch == "epoch-snapshot-publish-gap"
                )
            )
        ).all()
        assert len(rows) == 2
        original_ids = sorted(row.id for row in rows)

    monkeypatch.setattr(controller, "_persist", original_persist)
    fresh = receipt()
    assert fresh.provenance is not None
    fresh = replace(
        fresh,
        provenance=replace(
            fresh.provenance,
            fetch_id="fetch-snapshot-publish-gap-fresh",
            started_at=NOW + timedelta(seconds=29),
            observed_at=NOW + timedelta(seconds=30),
        ),
    )
    clock.current = NOW + timedelta(seconds=30)
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=fresh,
        membership_epoch="epoch-snapshot-publish-gap",
        p4_provenance=p4_provenance(),
    )
    assert state.snapshot_committed
    assert sorted(state.final_snapshot_ids) == original_ids
    assert companion.start_calls == 1
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(WorkspaceMemberFinalUsageSnapshot).where(
                    WorkspaceMemberFinalUsageSnapshot.membership_epoch == "epoch-snapshot-publish-gap"
                )
            )
        ).all()
        assert len(rows) == 2


async def test_start_pre_effect_accounting_failure_never_calls_companion_and_releases_child_scope(
    rotation_context,
    monkeypatch,
) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("accounting-hook-failure")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-accounting-hook-failure")

    async def reject_accounting(operation_id: str, effect: str) -> None:
        assert operation_id == quota.operation_id and effect == "remove"
        raise ValueError("synthetic quota became terminal")

    monkeypatch.setattr(controller, "_quota_request", reject_accounting)
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-accounting-hook-failure",
        p4_provenance=p4_provenance(),
    )
    assert companion.start_calls == 0
    assert state.phase == "needs_attention"
    child = await controls.get(state.member_switch_run_id)
    assert child is not None and child.active_scope is None and child.pending_action is None


async def test_start_preclaim_admission_rejection_closes_preview_before_releasing_quota(rotation_context) -> None:
    controller, _, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("start-preclaim-reject")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-start-preclaim-reject")
    companion.admission_results = [
        CompanionAdmission(can_start=True, code="ready"),
        CompanionAdmission(can_start=True, code="ready"),
        CompanionAdmission(can_start=False, code="busy"),
    ]

    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-start-preclaim-reject",
        p4_provenance=p4_provenance(),
    )
    assert companion.start_calls == 0
    assert state.phase == "needs_attention"
    assert state.last_code == "rotation_start_rejected:busy"
    child = await controls.get(state.member_switch_run_id)
    assert child is not None and child.active_scope is None and child.pending_action is None
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None and row.reservation_released_at is not None


async def test_stale_cleanup_cannot_release_quota_after_peer_claims_start(rotation_context, monkeypatch) -> None:
    controller, switch, controls, companion, sessions, clock = rotation_context
    _, weekly, reset = evidence("cleanup-race")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-cleanup-race")
    original_start_child = controller._start_child

    async def crash_before_start(record, state, run):
        raise RuntimeError("synthetic pre-start crash")

    monkeypatch.setattr(controller, "_start_child", crash_before_start)
    with pytest.raises(RuntimeError, match="synthetic pre-start crash"):
        await controller.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-cleanup-race",
            p4_provenance=p4_provenance(),
        )
    monkeypatch.setattr(controller, "_start_child", original_start_child)
    controller_id = rotation_controller_id("cleanup-race")
    await controller.resume(controller_id)

    stale = RotationController(controls, switch, sessions, sessions, clock=clock)
    healthy = RotationController(controls, switch, sessions, sessions, clock=clock)
    cleanup_entered = asyncio.Event()
    allow_cleanup = asyncio.Event()
    original_cleanup = stale._cancel_preeffect_run

    async def paused_cleanup(state, run):
        cleanup_entered.set()
        await allow_cleanup.wait()
        return await original_cleanup(state, run)

    monkeypatch.setattr(stale, "_cancel_preeffect_run", paused_cleanup)
    stale_task = asyncio.create_task(
        stale.evaluate_and_start(
            weekly=weekly,
            reset=reset,
            quota=quota,
            current_member=OUTGOING,
            final_usage_receipt=receipt(),
            membership_epoch="epoch-cleanup-race",
            p4_provenance=p4_provenance(version="2.11.48"),
        )
    )
    await cleanup_entered.wait()

    healthy_state = await healthy.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-cleanup-race",
        p4_provenance=p4_provenance(),
    )
    assert companion.start_calls == 1
    assert healthy_state.remove_state == "unknown"

    allow_cleanup.set()
    stale_state = await stale_task
    assert stale_state.phase in {"needs_attention", "removal_effect_unknown", "removing"}
    assert companion.start_calls == 1
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None
        assert row.reservation_released_at is None
        assert row.remove_effect == "unknown"
