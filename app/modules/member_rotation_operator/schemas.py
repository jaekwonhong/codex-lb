from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

FoundationState = Literal[
    "usage_unknown",
    "usage_available",
    "reset_required",
    "reset_recovered",
    "reset_reconciliation_pending",
    "reset_unavailable",
    "quota_required",
    "quota_blocked",
    "admission_ready",
    "invalid_evidence",
]
WeeklyState = Literal["unknown", "available", "exhausted"]
FiveHourState = Literal["observed", "not_provided", "unknown", "stale", "missing"]
ResetOperatorState = Literal[
    "resolution_required",
    "redeem_in_progress",
    "confirmed_no_redeemable_credit",
    "usage_recovered",
    "reconciliation_pending",
    "unavailable",
    "unknown",
]


class RotationOperatorMember(DashboardModel):
    preset_id: str = Field(min_length=1)
    email: str = Field(min_length=3)
    user_id: str = Field(min_length=1)


class RotationWeeklyUsageView(DashboardModel):
    state: WeeklyState
    reason: str | None = None


class RotationFiveHourUsageView(DashboardModel):
    state: FiveHourState
    used_percent: float | None = None
    reset_at: int | None = None
    observed_at: datetime | None = None


class RotationResetView(DashboardModel):
    state: ResetOperatorState
    detail: str | None = None


class RotationFoundationView(DashboardModel):
    state: FoundationState
    admission_ready: bool
    attention_required: bool
    weekly_state: WeeklyState
    weekly_reason: str | None = None
    reset_status: str | None = None
    quota_code: str | None = None
    count_24h: int | None = None
    count_168h: int | None = None


class RotationQuotaView(DashboardModel):
    count_24h: int = Field(ge=0)
    limit_24h: int = Field(ge=1)
    count_168h: int = Field(ge=0)
    limit_168h: int = Field(ge=1)
    count_basis: str
    history_complete: bool
    coverage_started_at: datetime | None = None


class HistoricalUsageWindowView(DashboardModel):
    logical_window: Literal["5h", "weekly"]
    source_window: str
    used_percent: float
    original_reset_at: int | None = None
    effective_reset_at: int | None = None
    observed_at: datetime
    retained_at: datetime
    reset_schedule_invalidated: bool


class RemovedMemberHistoryView(DashboardModel):
    email: str
    user_id: str
    preset_id: str
    membership_epoch: str
    removed_at: datetime | None = None
    retained_at: datetime
    five_hour_state: Literal["observed", "not_provided", "unknown"] = "unknown"
    five_hour: HistoricalUsageWindowView | None = None
    weekly: HistoricalUsageWindowView | None = None


class RotationControllerView(DashboardModel):
    status: str
    reason: str | None = None
    remove_effect: str | None = None
    invite_effect: str | None = None
    invitation_issued: bool | None = None
    membership_confirmed: bool | None = None
    companion_status: str | None = None


class RotationWorkspaceOperatorView(DashboardModel):
    workspace_id: str
    workspace_account_id: str
    workspace_name: str
    owner_email: str
    automatic_rotation_enabled: bool
    control_version: int = Field(ge=0)
    current_member: RotationOperatorMember | None = None
    weekly_usage: RotationWeeklyUsageView
    five_hour_usage: RotationFiveHourUsageView
    reset_credit: RotationResetView
    quota: RotationQuotaView
    foundation: RotationFoundationView | None = None
    controller: RotationControllerView
    next_candidate: RotationOperatorMember | None = None
    blocker_codes: list[str] = Field(default_factory=list)
    history: list[RemovedMemberHistoryView] = Field(default_factory=list)


class RotationOperatorResponse(DashboardModel):
    schema_version: Literal[1] = 1
    workspaces: list[RotationWorkspaceOperatorView]


class RotationIntentUpdateRequest(DashboardModel):
    enabled: bool
    expected_version: int = Field(ge=0)


class RotationIntentView(DashboardModel):
    workspace_id: str
    workspace_account_id: str
    enabled: bool
    version: int = Field(ge=1)
