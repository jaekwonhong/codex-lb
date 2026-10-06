from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import ConfigDict, Field

from app.modules.shared.schemas import DashboardModel
from app.modules.workspace_member_controller.domain import (
    Catalog as Catalog,
)
from app.modules.workspace_member_controller.domain import (
    CurrentMember as CurrentMember,
)
from app.modules.workspace_member_controller.domain import (
    Identity as Identity,
)
from app.modules.workspace_member_controller.domain import (
    Member as Member,
)
from app.modules.workspace_member_controller.domain import (
    MembershipObservation as MembershipObservation,
)
from app.modules.workspace_member_controller.domain import (
    MembershipObservationMember as MembershipObservationMember,
)
from app.modules.workspace_member_controller.domain import (
    OwnerAuthTarget as OwnerAuthTarget,
)
from app.modules.workspace_member_controller.domain import (
    Workspace as Workspace,
)

CONTROL_PROTOCOL = "managed_member_switch_v1"
OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY = "ego_lite_owner_membership_observation_v1"
OWNER_MEMBERSHIP_MUTATION_CAPABILITY = "ego_lite_owner_membership_mutation_v1"
RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY = "ego_lite_recipient_membership_lifecycle_v1"
EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY = "ego_lite_device_auth_automation_v1"
OWNER_OAUTH_ENROLLMENT_CAPABILITY = "ego_lite_owner_oauth_enrollment_v1"
AUTH_ENROLLMENT_PROTOCOL = "managed_member_auth_enrollment_v2"
ROTATION_CONTROLLER_PROTOCOL = "usage_member_rotation_controller_v1"
P4_TYPED_TELEMETRY_CONTRACT = "member_rotation_typed_telemetry_v1"
P4_TYPED_TELEMETRY_VERSION = "2.11.47"
P4_TYPED_TELEMETRY_BINARY_SHA256 = "0f7b665e47f1b2cd4959814afe3ee68fe0aa5cc25a264e295997d3499290f1ce"
P4_TYPED_TELEMETRY_OPS_COMMIT = "47ac829a23b9811537bcd2d21ae9b8003c9c464a"
CANARY_TELEMETRY_VERSION = "2.11.48-canary.1"
CANARY_TELEMETRY_BINARY_SHA256 = "1ec90e2b7315a9a19d718b03ff7c8ec54e90ff72aa9ca92b83a060fe0456b2d1"
CANARY_TELEMETRY_SOURCE_SHA256 = "b6f6c753595bbc09afcfb267e1d3a3660bf6fe54cb105b931095b4a19e6ef6e8"


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
    canary: bool = False


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


TelemetryPrimitive: TypeAlias = str | bool | int | float | None
MutationCaptureState: TypeAlias = Literal[
    "json",
    "empty_body",
    "json_parse_failure",
    "response_not_received",
    "transport_failure",
    "body_read_failure",
    "sanitization_failure",
    "capture_failure",
]


class MemberMutationResponseObservation(DashboardModel):
    """P4 sanitized response envelope; dict absence is distinct from JSON null."""

    event: Literal["remove_response", "invite_response"]
    capture_state: MutationCaptureState
    http_status: int | None = None
    fields: dict[str, TelemetryPrimitive] = Field(default_factory=dict)


class MemberRemovalObservationResponse(DashboardModel):
    """Typed server mirror of the P4 remove-only observation result."""

    accepted: bool
    code: str
    observation_id: str
    mutation_sent: bool
    outcome_unknown: bool
    immediate_response_ok: bool | None = None
    http_status: int | None = None
    removal_confirmed: bool
    stable_observations: int
    response_observation: MemberMutationResponseObservation | None = None


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
    invite_response_observation: MemberMutationResponseObservation | None = None
    invitation_non_effect_confirmed: bool = False


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
    remove_response_observation: MemberMutationResponseObservation | None = None


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
    rotation_controller_id: str | None = None


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


class CompanionTypedTelemetryProvenance(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    version: str
    binary_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ops_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    source_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @property
    def qualified(self) -> bool:
        if self.version == CANARY_TELEMETRY_VERSION:
            return (
                self.contract == P4_TYPED_TELEMETRY_CONTRACT
                and self.binary_sha256 == CANARY_TELEMETRY_BINARY_SHA256
                and self.source_manifest_sha256 == CANARY_TELEMETRY_SOURCE_SHA256
                and self.ops_commit is None
            )
        return (
            self.contract == P4_TYPED_TELEMETRY_CONTRACT
            and self.version == P4_TYPED_TELEMETRY_VERSION
            and self.binary_sha256 == P4_TYPED_TELEMETRY_BINARY_SHA256
            and self.ops_commit == P4_TYPED_TELEMETRY_OPS_COMMIT
            and self.source_manifest_sha256 is None
        )


RotationControllerPhase: TypeAlias = Literal[
    "foundation_evaluating",
    "snapshotting_outgoing",
    "removing",
    "removal_effect_unknown",
    "removal_confirmed",
    "inviting",
    "invite_effect_unknown",
    "invite_sent",
    "waiting_membership",
    "finalizing",
    "completed",
    "needs_attention",
]
RotationEffectState: TypeAlias = Literal["not_attempted", "unknown", "confirmed", "authoritative_non_effect"]


class RotationControllerState(DashboardModel):
    model_config = ConfigDict(extra="forbid")
    control_protocol: Literal["usage_member_rotation_controller_v1"] = ROTATION_CONTROLLER_PROTOCOL
    id: str
    evaluation_id: str
    workspace_id: str
    workspace_account_id: str
    outgoing_account_id: str
    outgoing_preset_id: str | None = None
    outgoing_email: str
    outgoing_user_id: str
    incoming: Identity | None = None
    foundation_state: str
    foundation_evidence_ref: str | None = None
    foundation_admission_ready: bool = False
    foundation_attention_required: bool = False
    foundation_weekly_state: Literal["unknown", "available", "exhausted"] = "unknown"
    foundation_weekly_reason: str | None = None
    reset_status: str | None = None
    foundation_quota_code: str | None = None
    foundation_count_24h: int | None = None
    foundation_count_168h: int | None = None
    quota_operation_id: str | None = None
    membership_epoch: str
    p4_provenance: CompanionTypedTelemetryProvenance | None = None
    p4_provenance_verified: bool = False
    snapshot_committed: bool = False
    final_snapshot_ids: list[str] = Field(default_factory=list)
    member_switch_run_id: str
    member_switch_operation_id: str | None = None
    start_command_id: str
    remove_state: RotationEffectState = "not_attempted"
    invite_state: RotationEffectState = "not_attempted"
    remove_response_observation: MemberMutationResponseObservation | None = None
    invite_response_observation: MemberMutationResponseObservation | None = None
    phase: RotationControllerPhase = "foundation_evaluating"
    last_code: str
    terminal_reason: str | None = None
    updated_at: datetime


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


class AuthEnrollmentPostProbe(DashboardModel):
    state: Literal["completed", "failed"]
    account_id: str | None = None
    probe_status_code: int | None = None
    primary_used_percent_after: float | None = None
    secondary_used_percent_after: float | None = None
    account_status_after: str | None = None
    usage_refresh_succeeded: bool | None = None
    error_code: str | None = None


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
    post_probe: AuthEnrollmentPostProbe | None = None
    post_probe_claim_id: str | None = None
    post_probe_claimed_at: datetime | None = None
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
    post_probe: AuthEnrollmentPostProbe | None = None
    flow_id: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    expires_in_seconds: int | None = None
    browser_profile_id: str | None = None
    browser_task_space_id: int | None = None
    browser_ownership: str | None = None


class ActiveAuthEnrollmentResponse(DashboardModel):
    enrollment: AuthEnrollmentView | None
