from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import (
    MemberRotationQuotaOperation,
    MemberSwitchControlRecord,
    WorkspaceMemberFinalUsageSnapshot,
)
from app.db.session import SessionLocal
from app.modules.member_switch.policy import membership_confirmed
from app.modules.member_switch.rotation_foundation import RotationFoundationReadModel, RotationFoundationState
from app.modules.member_switch.schemas import RotationControllerState, RunState

FiveHourState = Literal["observed", "unknown", "stale", "missing"]
ResetOperatorState = Literal[
    "resolution_required",
    "redeem_in_progress",
    "confirmed_no_redeemable_credit",
    "usage_recovered",
    "reconciliation_pending",
    "unavailable",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class OperatorMemberIdentity:
    preset_id: str
    email: str
    user_id: str


@dataclass(frozen=True, slots=True)
class OperatorFiveHourObservation:
    """Display evidence only. P6 never converts this into rotation eligibility."""

    state: FiveHourState
    used_percent: float | None = None
    reset_at: int | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RotationOperatorSnapshot:
    """Additive P5→P6 read adapter; no method on this contract can perform effects."""

    workspace_id: str
    workspace_account_id: str
    foundation: RotationFoundationReadModel | None = None
    current_member: OperatorMemberIdentity | None = None
    five_hour: OperatorFiveHourObservation | None = None
    reset_state: ResetOperatorState | None = None
    reset_detail: str | None = None
    controller_status: str = "idle"
    controller_reason: str | None = None
    remove_effect: str | None = None
    invite_effect: str | None = None
    next_candidate: OperatorMemberIdentity | None = None
    blocker_codes: tuple[str, ...] = ()
    invitation_issued: bool | None = None
    membership_confirmed: bool | None = None
    companion_status: str | None = None
    removed_at_by_membership_epoch: Mapping[str, datetime] = field(default_factory=dict)


class RotationOperatorSnapshotAdapter(Protocol):
    async def snapshot(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
    ) -> RotationOperatorSnapshot | None: ...


class NullRotationOperatorSnapshotAdapter:
    async def snapshot(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
    ) -> RotationOperatorSnapshot | None:
        del workspace_id, workspace_account_id
        return None


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _operator_identity(
    preset_id: str | None,
    email: str | None,
    user_id: str | None,
) -> OperatorMemberIdentity | None:
    if not preset_id or not email or not user_id:
        return None
    return OperatorMemberIdentity(preset_id=preset_id, email=email.casefold(), user_id=user_id)


class DurableRotationOperatorSnapshotAdapter:
    """Read-only projection from the durable P5 controller/run state into P6.

    The adapter never evaluates eligibility and never owns an effect. It only
    projects facts that P5 already persisted plus immutable/history rows.
    """

    async def snapshot(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
    ) -> RotationOperatorSnapshot | None:
        async with SessionLocal() as session:
            rows = list(
                (
                    await session.scalars(
                        select(MemberSwitchControlRecord).where(MemberSwitchControlRecord.kind == "rotation")
                    )
                ).all()
            )
            states: list[RotationControllerState] = []
            for row in rows:
                try:
                    state = RotationControllerState.model_validate_json(row.payload)
                except ValidationError:
                    continue
                if state.workspace_id == workspace_id and state.workspace_account_id == workspace_account_id:
                    states.append(state)
            if not states:
                return None
            state = max(states, key=lambda item: item.updated_at)

            run_state: RunState | None = None
            run_row = await session.get(MemberSwitchControlRecord, state.member_switch_run_id)
            if run_row is not None and run_row.kind == "run":
                try:
                    run_state = RunState.model_validate_json(run_row.payload)
                except ValidationError:
                    run_state = None

            joined = bool(
                run_state is not None and run_state.operation is not None and membership_confirmed(run_state.operation)
            )
            incoming = (
                None
                if state.incoming is None
                else _operator_identity(
                    state.incoming.preset_id,
                    state.incoming.target_email,
                    state.incoming.target_user_id,
                )
            )
            outgoing = _operator_identity(
                state.outgoing_preset_id,
                state.outgoing_email,
                state.outgoing_user_id,
            )
            current_member = (
                incoming
                if joined
                else outgoing
                if state.remove_state in {"not_attempted", "authoritative_non_effect"}
                else None
            )

            five_hour: OperatorFiveHourObservation | None = None
            if current_member == outgoing and state.final_snapshot_ids:
                snapshot_rows = list(
                    (
                        await session.scalars(
                            select(WorkspaceMemberFinalUsageSnapshot).where(
                                WorkspaceMemberFinalUsageSnapshot.id.in_(state.final_snapshot_ids)
                            )
                        )
                    ).all()
                )
                five = next((row for row in snapshot_rows if row.logical_window == "5h"), None)
                if five is not None:
                    five_hour = OperatorFiveHourObservation(
                        state="observed",
                        used_percent=five.used_percent,
                        reset_at=five.reset_at,
                        observed_at=_aware_utc(five.observed_at),
                    )

            try:
                foundation_state = RotationFoundationState(state.foundation_state)
            except ValueError:
                foundation = None
            else:
                foundation = RotationFoundationReadModel(
                    state=foundation_state,
                    admission_ready=state.foundation_admission_ready,
                    attention_required=state.foundation_attention_required,
                    weekly_state=state.foundation_weekly_state,
                    weekly_reason=state.foundation_weekly_reason,
                    reset_status=state.reset_status,
                    quota_code=state.foundation_quota_code,
                    count_24h=state.foundation_count_24h,
                    count_168h=state.foundation_count_168h,
                )

            removed_at: dict[str, datetime] = {}
            if state.quota_operation_id:
                quota = await session.get(MemberRotationQuotaOperation, state.quota_operation_id)
                if quota is not None and quota.remove_effect == "confirmed" and quota.remove_effect_at is not None:
                    observed = _aware_utc(quota.remove_effect_at)
                    if observed is not None:
                        removed_at[state.membership_epoch] = observed

            if state.p4_provenance is None:
                companion_status = "capability_mismatch"
            elif state.p4_provenance.qualified:
                companion_status = "qualified"
            else:
                companion_status = "provenance_mismatch"

            blockers: list[str] = []
            if state.phase == "needs_attention":
                blockers.append(state.terminal_reason or state.last_code)
            if companion_status != "qualified":
                blockers.append(f"companion_{companion_status}")

            invitation_issued = (
                True if state.invite_state == "confirmed" else None if state.invite_state == "unknown" else False
            )
            membership_state = True if joined else False if invitation_issued is True else None

            return RotationOperatorSnapshot(
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                foundation=foundation,
                current_member=current_member,
                five_hour=five_hour,
                controller_status=state.phase,
                controller_reason=state.terminal_reason or state.last_code,
                remove_effect=state.remove_state,
                invite_effect=state.invite_state,
                next_candidate=incoming if state.phase != "completed" else None,
                blocker_codes=tuple(dict.fromkeys(blockers)),
                invitation_issued=invitation_issued,
                membership_confirmed=membership_state,
                companion_status=companion_status,
                removed_at_by_membership_epoch=removed_at,
            )


_snapshot_adapter: RotationOperatorSnapshotAdapter = DurableRotationOperatorSnapshotAdapter()


def get_rotation_operator_snapshot_adapter() -> RotationOperatorSnapshotAdapter:
    return _snapshot_adapter


def set_rotation_operator_snapshot_adapter(adapter: RotationOperatorSnapshotAdapter) -> None:
    """Integration seam for P5 and tests; registering an adapter performs no work by itself."""

    global _snapshot_adapter
    _snapshot_adapter = adapter
