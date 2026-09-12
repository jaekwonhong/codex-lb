from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.modules.shared.schemas import DashboardModel

CONTROL_PROTOCOL = "managed_member_switch_v1"
OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY = "ego_lite_owner_membership_observation_v1"
OWNER_MEMBERSHIP_MUTATION_CAPABILITY = "ego_lite_owner_membership_mutation_v1"
RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY = "ego_lite_recipient_membership_lifecycle_v1"
EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY = "ego_lite_device_auth_automation_v1"
AUTH_ENROLLMENT_PROTOCOL = "managed_member_auth_enrollment_v2"


class AdmissionBlocker(DashboardModel):
    kind: str
    record_id: str
    code: str


class LocalAdmission(DashboardModel):
    can_create: bool
    blockers: list[AdmissionBlocker]


class CompanionAdmission(DashboardModel):
    can_start: bool
    code: str
    operation_id: str | None = None
    client_flow_id: str | None = None


class Member(DashboardModel):
    preset_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")


class CurrentMember(DashboardModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    preset_id: str | None = None
    auth_state: Literal[
        "active",
        "handoff_quarantined",
        "inactive",
        "absent",
        "ambiguous",
        "unmanaged",
        "unknown",
    ] = "unknown"
    auth_account_id: str | None = None


class Workspace(DashboardModel):
    id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    workspace_name: str = Field(min_length=1)
    owner_email: str = Field(min_length=3)
    members: list[Member]
    current_members: list[CurrentMember] = Field(default_factory=list)
    membership_code: str = "not_checked"
    membership_observed_at: datetime | None = None


class Catalog(DashboardModel):
    enabled: bool
    schema_version: Literal[1]
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    capabilities: list[str] = Field(default_factory=list)
    workspaces: list[Workspace]


class MembershipObservationMember(DashboardModel):
    email: str
    user_id: str
    preset_id: str | None = None
    classification: str


class MembershipObservation(DashboardModel):
    schema_version: Literal[1]
    available: bool
    code: str
    workspace_id: str
    workspace_account_id: str
    catalog_fingerprint: str
    observed_at: datetime
    complete: bool
    owner_verified: bool
    identity_ambiguous: bool
    partial_identity: bool
    duplicate_identity: bool
    unknown_member: bool
    members: list[MembershipObservationMember]


class Identity(DashboardModel):
    workspace_id: str
    workspace_account_id: str
    preset_id: str
    target_email: str
    target_user_id: str
    catalog_fingerprint: str


class PreviewRequest(DashboardModel):
    workspace_account_id: str
    preset_id: str
    catalog_fingerprint: str


class Preview(DashboardModel):
    ready: bool
    code: str
    preview_token: str | None
    expires_at: datetime | None
    workspace_name: str | None
    owner_email: str | None
    target_email: str | None
    remove_email: str | None
    catalog_fingerprint: str | None


class StartRequest(DashboardModel):
    preview_token: str
    client_flow_id: str


class StartReceipt(DashboardModel):
    accepted: bool
    code: str
    operation_id: str | None
    blocking_operation_id: str | None = None


class OperationTraceEntry(DashboardModel):
    sequence: int
    stage: str
    code: str
    at: datetime
    action: str | None = None
    status: int | None = None


class InvitationSettlement(DashboardModel):
    invitation_issued: bool
    automatic_observation_attempts: int
    automatic_settlement_confirmed: bool
    pending_invitation_id: str | None
    fallback_used: bool
    final_membership_confirmed: bool
    invitation_attempted: bool = False
    recipient_workspace_refresh_attempts: int = 0
    recipient_workspace_observed: bool = False


class Operation(DashboardModel):
    operation_id: str = Field(min_length=1)
    member_switch_operation_id: str = Field(min_length=1)
    workspace_id: str
    workspace_account_id: str
    target_email: str
    target_user_id: str
    stage: str
    code: str
    removed_email: str | None
    removed_user_id: str | None
    membership_state: Literal["unknown", "active"]
    updated_at: datetime
    trace: list[OperationTraceEntry] = Field(default_factory=list)
    invitation_settlement: InvitationSettlement | None = None


class RecipientReceipt(DashboardModel):
    ready: bool
    code: str
    target_email: str | None
    outcome_unknown: bool


class BrowserReceipt(DashboardModel):
    accepted: bool
    code: str
    browser_operation_id: str | None
    target_email: str | None
    outcome_unknown: bool


class CloseReceipt(DashboardModel):
    closed: bool
    code: str
    outcome_unknown: bool


class FinalizeReceipt(DashboardModel):
    released: bool
    code: str


class EgoOAuthBrowserIdentityRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    enrollment_id: str
    workspace_id: str
    workspace_account_id: str
    preset_id: str
    target_email: str
    target_user_id: str
    catalog_fingerprint: str
    verification_url: str


class EgoOAuthBrowserRequest(EgoOAuthBrowserIdentityRequest):
    user_code: str


class EgoOAuthBrowserStatusRequest(EgoOAuthBrowserIdentityRequest):
    pass


class EgoOAuthBrowserResponse(DashboardModel):
    accepted: bool
    state: str
    code: str
    enrollment_id: str
    profile_id: str
    task_space_id: int | None = None
    ownership: str | None = None
    outcome_unknown: bool = False


class EgoOAuthProfileRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    workspace_account_id: str
    preset_id: str
    target_email: str
    target_user_id: str
    catalog_fingerprint: str


class EgoOAuthProfileResponse(DashboardModel):
    ready: bool
    code: str
    profile_id: str


ParticipantAction = Literal["prepare_session", "open_browser", "close_browser"]


class ParticipantRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    client_flow_id: str
    action: ParticipantAction
    member_switch_operation_id: str
    identity: Identity
    browser_operation_id: str | None = None
    verification_url: str | None = None
    user_code: str | None = None


class ParticipantReceipt(DashboardModel):
    schema_version: Literal[1]
    command_id: str
    client_flow_id: str
    action: ParticipantAction
    member_switch_operation_id: str
    identity: Identity
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["pending", "completed"]
    code: str
    recorded_at: datetime
    browser_operation_id: str | None
    session: RecipientReceipt | None = None
    browser: BrowserReceipt | None = None
    close: CloseReceipt | None = None


Action = Literal[
    "start",
    "observe_membership",
    "prepare_session",
    "prepare_auth",
    "open_browser",
    "observe_auth",
    "advance_auth",
    "close_browser",
    "finish",
    "cancel",
    "reconcile",
]
Phase = Literal[
    "previewed",
    "membership_requested",
    "membership_confirmed",
    "session_prepared",
    "auth_prepared",
    "auth_browser_opened",
    "auth_confirmed",
    "completed",
    "needs_attention",
    "failed",
]


class CreateRunRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    workspace_id: str = Field(min_length=1, max_length=100)
    preset_id: str = Field(min_length=1, max_length=100)
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class CommandRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_revision: int = Field(ge=0)
    action: Action


class RunState(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    control_protocol: str | None = None
    id: str
    create_request_hash: str
    identity: Identity
    phase: Phase
    last_code: str
    updated_at: datetime
    preview: Preview | None = None
    operation: Operation | None = None
    operation_id: str | None = None
    handoff_id: str | None = None
    auth_state: str | None = None
    browser_operation_id: str | None = None
    browser_flow_id: str | None = None
    participant_request_hash: str | None = None


class RunView(DashboardModel):
    id: str
    revision: int
    identity: Identity
    phase: str
    last_code: str
    updated_at: datetime
    pending_action: str | None
    allowed_actions: list[Action]
    removed_email: str | None = None
    operation: Operation | None
    operation_id: str | None
    handoff_id: str | None
    auth_state: str | None
    browser_operation_id: str | None


class ActiveRunResponse(DashboardModel):
    run: RunView | None


AuthEnrollmentAction = Literal[
    "prepare_auth",
    "open_auth_browser",
    "advance_auth",
    "finish",
    "cancel",
    "reconcile",
]
AuthEnrollmentPhase = Literal[
    "prepared",
    "auth_prepared",
    "auth_browser_opened",
    "auth_confirmed",
    "completed",
    "needs_attention",
]


class AuthEnrollmentCreateRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    enrollment_id: UUID
    workspace_id: str = Field(min_length=1, max_length=100)
    preset_id: str = Field(min_length=1, max_length=100)
    member_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    member_user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class AuthEnrollmentCommandRequest(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_revision: int = Field(ge=0)
    action: AuthEnrollmentAction


class AuthEnrollmentState(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    control_protocol: str | None = None
    id: str
    create_request_hash: str
    identity: Identity
    operation_id: str
    phase: AuthEnrollmentPhase
    last_code: str
    updated_at: datetime
    handoff_id: str | None = None
    auth_state: str | None = None
    auth_account_id: str | None = None
    flow_id: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    expires_in_seconds: int | None = None
    browser_profile_id: str | None = None
    browser_task_space_id: int | None = None
    browser_ownership: str | None = None


class AuthEnrollmentView(DashboardModel):
    id: str
    revision: int
    identity: Identity
    phase: str
    last_code: str
    updated_at: datetime
    pending_action: str | None
    allowed_actions: list[AuthEnrollmentAction]
    handoff_id: str | None = None
    auth_state: str | None = None
    auth_account_id: str | None = None
    flow_id: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    expires_in_seconds: int | None = None
    browser_profile_id: str | None = None
    browser_task_space_id: int | None = None
    browser_ownership: str | None = None


class ActiveAuthEnrollmentResponse(DashboardModel):
    enrollment: AuthEnrollmentView | None
