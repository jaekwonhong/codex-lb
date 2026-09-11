from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.modules.shared.schemas import DashboardModel

HandoffState = Literal[
    "prepared",
    "old_auth_quarantined",
    "device_code_issued",
    "browser_opened",
    "user_action_required",
    "oauth_pending",
    "oauth_verified",
    "old_auth_deleted",
    "completed",
    "failed",
]
MemberUsageAvailability = Literal[
    "available",
    "auth_unavailable",
    "usage_unavailable",
    "ambiguous_auth",
]
AuthObservationState = Literal[
    "active",
    "handoff_quarantined",
    "inactive",
    "absent",
    "ambiguous",
]
MemberAuthReconciliationAction = Literal[
    "cleanup_old_auth",
    "unpause_target_auth",
]


class MemberAuthHandoffPrepareRequest(DashboardModel):
    member_switch_operation_id: str = Field(min_length=1)
    preset_id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    removed_email: str | None = None
    removed_user_id: str | None = None
    target_email: str = Field(min_length=3)
    target_user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    membership_state: Literal["active"]
    catalog_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    preserve_other_auth: bool = False

    @model_validator(mode="after")
    def validate_removed_identity(self) -> "MemberAuthHandoffPrepareRequest":
        if (self.removed_email is None) != (self.removed_user_id is None):
            raise ValueError("Removed email and user ID must be provided together")
        if self.preserve_other_auth and self.removed_email is not None:
            raise ValueError("OAuth-only enrollment cannot identify an auth to remove")
        return self


class MemberAuthReconciliationRequest(DashboardModel):
    action: MemberAuthReconciliationAction
    workspace_id: str = Field(min_length=1)
    preset_id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    target_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    target_user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    membership_state: Literal["active"]
    catalog_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")

    @field_validator("target_email", mode="before")
    @classmethod
    def normalize_target_email(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class MemberAuthReconciliationResponse(DashboardModel):
    accepted: bool
    code: str
    action: MemberAuthReconciliationAction


class MemberAuthUsageSnapshot(DashboardModel):
    remaining_percent: float | None = None
    reset_at: datetime | None = None
    observed_at: datetime | None = None


class WorkspaceAuthObservationMember(DashboardModel):
    preset_id: str
    email: str
    user_id: str
    state: AuthObservationState
    auth_account_id: str | None = None
    auth_status: str | None = None
    deactivation_reason: str | None = None
    usage: MemberAuthUsageSnapshot | None = None


class WorkspaceAuthObservationResponse(DashboardModel):
    schema_version: Literal[1] = 1
    available: bool
    code: str
    workspace_id: str
    workspace_account_id: str
    catalog_fingerprint: str
    observed_at: datetime
    refresh_available: bool
    active_auth_count: int
    identity_ambiguous: bool
    members: list[WorkspaceAuthObservationMember]


class CatalogMemberUsage(DashboardModel):
    workspace_id: str
    preset_id: str
    workspace_account_id: str
    email: str
    user_id: str
    auth_account_id: str | None = None
    auth_status: str | None = None
    availability: MemberUsageAvailability
    remaining_percent: float | None = None
    reset_at: datetime | None = None
    observed_at: datetime | None = None


class CatalogMemberUsageResponse(DashboardModel):
    members: list[CatalogMemberUsage]


class CatalogMemberRegistrationRequest(DashboardModel):
    workspace_id: str = Field(min_length=1)
    preset_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")

    @field_validator("workspace_id", "preset_id", "display_name", "user_id", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class CatalogMemberIdentity(DashboardModel):
    workspace_id: str
    preset_id: str
    display_name: str
    email: str
    user_id: str
    workspace_account_id: str


class CatalogMemberRegistrationResponse(DashboardModel):
    accepted: bool
    code: str
    member: CatalogMemberIdentity


class MemberAuthHandoffResponse(DashboardModel):
    revision: int = 0
    pending_action: str | None = None
    last_command_id: str | None = None
    handoff_id: str
    member_switch_operation_id: str
    preset_id: str
    workspace_account_id: str
    target_email: str
    target_user_id: str
    removed_email: str | None = None
    removed_auth_usage_snapshot: MemberAuthUsageSnapshot | None = None
    state: HandoffState
    flow_id: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    expires_in_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class MemberRotationEvent(DashboardModel):
    event_id: str
    workspace_id: str
    workspace_account_id: str
    preset_id: str
    email: str
    user_id: str
    catalog_fingerprint: str
    first_zero_at: datetime
    confirmed_zero_at: datetime
    claim_token: str
    claim_expires_at: datetime


class MemberRotationEventClaimResponse(DashboardModel):
    claimed: bool
    event: MemberRotationEvent | None = None


class MemberRotationEventSettleRequest(DashboardModel):
    claim_token: str = Field(min_length=1)
    processed: bool


class MemberRotationEventSettleResponse(DashboardModel):
    accepted: bool
