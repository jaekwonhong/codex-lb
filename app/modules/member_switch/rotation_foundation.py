from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol, TypedDict

from app.core.usage.weekly_observation import (
    RotationUsageObservation,
    UsageAccountIdentity,
    WeeklyUsageAssessment,
    WeeklyUsageObservation,
)
from app.modules.member_auth_handoff.rotation_events import RotationQuotaDecision, RotationQuotaRepository
from app.modules.member_auth_handoff.usage_snapshot_repository import FinalUsageSnapshotInput
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditResolution,
    RotationResetCreditResolutionStatus,
    WeeklyRecoveryState,
)


class RotationFoundationState(StrEnum):
    USAGE_UNKNOWN = "usage_unknown"
    USAGE_AVAILABLE = "usage_available"
    RESET_REQUIRED = "reset_required"
    RESET_RECOVERED = "reset_recovered"
    RESET_RECONCILIATION_PENDING = "reset_reconciliation_pending"
    RESET_UNAVAILABLE = "reset_unavailable"
    QUOTA_REQUIRED = "quota_required"
    QUOTA_BLOCKED = "quota_blocked"
    ADMISSION_READY = "admission_ready"
    INVALID_EVIDENCE = "invalid_evidence"


@dataclass(frozen=True, slots=True)
class RotationEvaluationIdentity:
    evaluation_id: str
    workspace_id: str
    member: UsageAccountIdentity
    redeem_request_id: str

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ValueError("evaluation_id must not be empty")
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must not be empty")
        if not self.redeem_request_id.strip():
            raise ValueError("redeem_request_id must not be empty")
        if not (
            self.member.account_id.strip()
            and self.member.workspace_account_id
            and self.member.workspace_account_id.strip()
            and self.member.user_id
            and self.member.user_id.strip()
            and self.member.email.strip()
        ):
            raise ValueError("rotation evaluation requires complete member identity")

    @property
    def workspace_account_id(self) -> str:
        assert self.member.workspace_account_id is not None
        return self.member.workspace_account_id


@dataclass(frozen=True, slots=True)
class RotationWeeklyEvidence:
    evaluation: RotationEvaluationIdentity
    observation: WeeklyUsageObservation
    not_before: datetime | None = None

    def assess(
        self,
        current_member: UsageAccountIdentity,
        *,
        now: datetime,
    ) -> WeeklyUsageAssessment:
        if not self.evaluation.member.matches(current_member):
            return WeeklyUsageAssessment("unknown", "identity_mismatch")
        return self.observation.assess(
            current_member,
            now=now,
            not_before=self.not_before,
        )


@dataclass(frozen=True, slots=True)
class RotationResetEvidence:
    evaluation: RotationEvaluationIdentity
    resolution: RotationResetCreditResolution


@dataclass(frozen=True, slots=True)
class RotationQuotaReservationEvidence:
    evaluation: RotationEvaluationIdentity
    operation_id: str
    decision: RotationQuotaDecision


@dataclass(frozen=True, slots=True)
class RotationFoundationReadModel:
    state: RotationFoundationState
    admission_ready: bool
    attention_required: bool
    weekly_state: str
    weekly_reason: str | None
    reset_status: str | None = None
    quota_code: str | None = None
    count_24h: int | None = None
    count_168h: int | None = None


class RotationUsageFetch(Protocol):
    async def __call__(self) -> RotationUsageObservation: ...


class CurrentUsageMemberResolver(Protocol):
    async def __call__(self) -> UsageAccountIdentity | None: ...


class FinalUsageRetentionUnavailable(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _QuotaFields(TypedDict):
    quota_code: str | None
    count_24h: int | None
    count_168h: int | None


def weekly_recovery_state(assessment: WeeklyUsageAssessment) -> WeeklyRecoveryState:
    if assessment.state == "available":
        return WeeklyRecoveryState.RECOVERED
    if assessment.state == "exhausted":
        return WeeklyRecoveryState.EXHAUSTED
    return WeeklyRecoveryState.UNKNOWN


def bind_rotation_weekly_evidence(
    receipt: RotationUsageObservation,
    evaluation: RotationEvaluationIdentity,
    *,
    not_before: datetime | None = None,
) -> RotationWeeklyEvidence:
    return RotationWeeklyEvidence(
        evaluation=evaluation,
        observation=receipt.weekly_observation,
        not_before=not_before,
    )


def bind_rotation_reset_resolution(
    evaluation: RotationEvaluationIdentity,
    resolution: RotationResetCreditResolution,
) -> RotationResetEvidence:
    if resolution.redeem_request_id != evaluation.redeem_request_id:
        raise ValueError("reset resolution request does not match rotation evaluation")
    if (
        resolution.account_id != evaluation.member.account_id
        or resolution.workspace_account_id != evaluation.workspace_account_id
    ):
        raise ValueError("reset resolution identity does not match rotation evaluation")
    return RotationResetEvidence(evaluation=evaluation, resolution=resolution)


def build_weekly_recovery_observer(
    fetch_usage: RotationUsageFetch,
    resolve_current_member: CurrentUsageMemberResolver,
    *,
    evaluation: RotationEvaluationIdentity,
    not_before: datetime,
    clock: Callable[[], datetime],
) -> Callable[[], Awaitable[WeeklyRecoveryState]]:
    """Adapt P1 same-fetch evidence to P2 while re-resolving identity per attempt."""

    async def observe() -> WeeklyRecoveryState:
        receipt = await fetch_usage()
        current_member = await resolve_current_member()
        if current_member is None:
            return WeeklyRecoveryState.UNKNOWN
        evidence = bind_rotation_weekly_evidence(
            receipt,
            evaluation,
            not_before=not_before,
        )
        return weekly_recovery_state(
            evidence.assess(
                current_member,
                now=clock(),
            )
        )

    return observe


async def reserve_rotation_quota(
    repository: RotationQuotaRepository,
    *,
    weekly: RotationWeeklyEvidence,
    reset: RotationResetEvidence,
    current_member: UsageAccountIdentity,
    now: datetime,
    operation_id: str,
    rotation_event_id: str | None = None,
) -> RotationQuotaReservationEvidence:
    """Reserve P3 quota only after exact exhausted/no-credit evidence is bound."""
    prerequisite = evaluate_rotation_foundation(
        weekly,
        current_member=current_member,
        now=now,
        reset=reset,
    )
    if prerequisite.state is not RotationFoundationState.QUOTA_REQUIRED:
        raise ValueError("rotation quota reservation prerequisites are not satisfied")
    evaluation = weekly.evaluation
    decision = await repository.reserve(
        operation_id=operation_id,
        workspace_id=evaluation.workspace_id,
        workspace_account_id=evaluation.workspace_account_id,
        rotation_event_id=rotation_event_id,
    )
    return RotationQuotaReservationEvidence(
        evaluation=evaluation,
        operation_id=operation_id,
        decision=decision,
    )


def evaluate_rotation_foundation(
    weekly: RotationWeeklyEvidence,
    *,
    current_member: UsageAccountIdentity,
    now: datetime,
    reset: RotationResetEvidence | None = None,
    quota: RotationQuotaReservationEvidence | None = None,
) -> RotationFoundationReadModel:
    """Pure admission decision. This function has no membership/OAuth/reset side effects."""
    evaluation = weekly.evaluation
    weekly_assessment = weekly.assess(current_member, now=now)
    reset_resolution = reset.resolution if reset is not None else None
    reset_status = reset_resolution.status.value if reset_resolution is not None else None
    quota_fields = _quota_fields(quota)

    if (
        (reset is not None and reset.evaluation != evaluation)
        or (reset_resolution is not None and reset_resolution.redeem_request_id != evaluation.redeem_request_id)
        or (
            reset_resolution is not None
            and (
                reset_resolution.account_id != evaluation.member.account_id
                or reset_resolution.workspace_account_id != evaluation.workspace_account_id
            )
        )
        or (quota is not None and quota.evaluation != evaluation)
    ):
        return RotationFoundationReadModel(
            state=RotationFoundationState.INVALID_EVIDENCE,
            admission_ready=False,
            attention_required=True,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )

    if reset_resolution is None:
        if quota is not None:
            return RotationFoundationReadModel(
                state=RotationFoundationState.INVALID_EVIDENCE,
                admission_ready=False,
                attention_required=True,
                weekly_state=weekly_assessment.state,
                weekly_reason=weekly_assessment.reason,
                **quota_fields,
            )
        if weekly_assessment.state == "unknown":
            return RotationFoundationReadModel(
                state=RotationFoundationState.USAGE_UNKNOWN,
                admission_ready=False,
                attention_required=True,
                weekly_state=weekly_assessment.state,
                weekly_reason=weekly_assessment.reason,
            )
        if weekly_assessment.state == "available":
            return RotationFoundationReadModel(
                state=RotationFoundationState.USAGE_AVAILABLE,
                admission_ready=False,
                attention_required=False,
                weekly_state=weekly_assessment.state,
                weekly_reason=weekly_assessment.reason,
            )
        return RotationFoundationReadModel(
            state=RotationFoundationState.RESET_REQUIRED,
            admission_ready=False,
            attention_required=False,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
        )

    if reset_resolution.status is RotationResetCreditResolutionStatus.USAGE_RECOVERED:
        return RotationFoundationReadModel(
            state=(
                RotationFoundationState.INVALID_EVIDENCE
                if quota is not None
                else RotationFoundationState.RESET_RECOVERED
            ),
            admission_ready=False,
            attention_required=quota is not None,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if reset_resolution.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING:
        return RotationFoundationReadModel(
            state=RotationFoundationState.RESET_RECONCILIATION_PENDING,
            admission_ready=False,
            attention_required=True,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if reset_resolution.status is RotationResetCreditResolutionStatus.UNAVAILABLE:
        return RotationFoundationReadModel(
            state=RotationFoundationState.RESET_UNAVAILABLE,
            admission_ready=False,
            attention_required=True,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if reset_resolution.status is not RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT:
        return RotationFoundationReadModel(
            state=RotationFoundationState.INVALID_EVIDENCE,
            admission_ready=False,
            attention_required=True,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if weekly_assessment.state == "unknown":
        return RotationFoundationReadModel(
            state=RotationFoundationState.USAGE_UNKNOWN,
            admission_ready=False,
            attention_required=True,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if weekly_assessment.state == "available":
        return RotationFoundationReadModel(
            state=(
                RotationFoundationState.INVALID_EVIDENCE
                if quota is not None
                else RotationFoundationState.USAGE_AVAILABLE
            ),
            admission_ready=False,
            attention_required=quota is not None,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if quota is None:
        return RotationFoundationReadModel(
            state=RotationFoundationState.QUOTA_REQUIRED,
            admission_ready=False,
            attention_required=False,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
        )
    if not quota.operation_id.strip():
        return RotationFoundationReadModel(
            state=RotationFoundationState.INVALID_EVIDENCE,
            admission_ready=False,
            attention_required=True,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    if not quota.decision.admitted:
        return RotationFoundationReadModel(
            state=RotationFoundationState.QUOTA_BLOCKED,
            admission_ready=False,
            attention_required=False,
            weekly_state=weekly_assessment.state,
            weekly_reason=weekly_assessment.reason,
            reset_status=reset_status,
            **quota_fields,
        )
    return RotationFoundationReadModel(
        state=RotationFoundationState.ADMISSION_READY,
        admission_ready=True,
        attention_required=False,
        weekly_state=weekly_assessment.state,
        weekly_reason=weekly_assessment.reason,
        reset_status=reset_status,
        **quota_fields,
    )


def final_usage_snapshot_inputs(
    receipt: RotationUsageObservation,
    evaluation: RotationEvaluationIdentity,
    current_member: UsageAccountIdentity,
    *,
    now: datetime,
    not_before: datetime | None = None,
) -> tuple[FinalUsageSnapshotInput, FinalUsageSnapshotInput]:
    """Build immutable P3 inputs only from one exact, fresh P1 fetch receipt."""
    if not evaluation.member.matches(current_member):
        raise FinalUsageRetentionUnavailable("identity_mismatch")
    weekly_assessment = receipt.weekly_observation.assess(
        current_member,
        now=now,
        not_before=not_before,
    )
    if weekly_assessment.state == "unknown":
        raise FinalUsageRetentionUnavailable(weekly_assessment.reason or "weekly_unknown")
    provenance = receipt.provenance
    five_hour = receipt.five_hour_window
    weekly = receipt.weekly_window
    if provenance is None:
        raise FinalUsageRetentionUnavailable("fetch_not_observed")
    if five_hour is None:
        raise FinalUsageRetentionUnavailable("five_hour_missing")
    if weekly is None:
        raise FinalUsageRetentionUnavailable("weekly_missing")
    current_time = _utc(now)
    five_hour_used = five_hour.raw_used_percent
    if five_hour_used is None or not math.isfinite(five_hour_used) or five_hour_used < 0:
        raise FinalUsageRetentionUnavailable("five_hour_usage_invalid")
    if five_hour.window_minutes != 300:
        raise FinalUsageRetentionUnavailable("five_hour_window_invalid")
    if five_hour.reset_at is None:
        raise FinalUsageRetentionUnavailable("five_hour_reset_missing")
    if five_hour.reset_at <= current_time.timestamp():
        raise FinalUsageRetentionUnavailable("five_hour_reset_elapsed")
    assert weekly.raw_used_percent is not None
    assert weekly.window_minutes is not None
    provenance_text = _provenance_json(receipt, evaluation)
    source_email = evaluation.member.email.strip().casefold()
    return (
        FinalUsageSnapshotInput(
            logical_window="5h",
            source_window=five_hour.source_slot,
            source_workspace_id=evaluation.workspace_id,
            source_workspace_account_id=evaluation.workspace_account_id,
            source_account_id=evaluation.member.account_id,
            source_user_id=evaluation.member.user_id or "",
            source_email=source_email,
            used_percent=five_hour_used,
            reset_at=five_hour.reset_at,
            window_minutes=five_hour.window_minutes,
            observed_at=provenance.observed_at,
            fetch_provenance=provenance_text,
            fetch_succeeded=receipt.fetch_succeeded,
            usage_written=receipt.usage_written,
        ),
        FinalUsageSnapshotInput(
            logical_window="weekly",
            source_window=weekly.source_slot,
            source_workspace_id=evaluation.workspace_id,
            source_workspace_account_id=evaluation.workspace_account_id,
            source_account_id=evaluation.member.account_id,
            source_user_id=evaluation.member.user_id or "",
            source_email=source_email,
            used_percent=weekly.raw_used_percent,
            reset_at=weekly.reset_at,
            window_minutes=weekly.window_minutes,
            observed_at=provenance.observed_at,
            fetch_provenance=provenance_text,
            fetch_succeeded=receipt.fetch_succeeded,
            usage_written=receipt.usage_written,
        ),
    )


def _quota_fields(quota: RotationQuotaReservationEvidence | None) -> _QuotaFields:
    if quota is None:
        return {"quota_code": None, "count_24h": None, "count_168h": None}
    return {
        "quota_code": quota.decision.code,
        "count_24h": quota.decision.count_24h,
        "count_168h": quota.decision.count_168h,
    }


def _provenance_json(
    receipt: RotationUsageObservation,
    evaluation: RotationEvaluationIdentity,
) -> str:
    provenance = receipt.provenance
    if provenance is None:
        raise FinalUsageRetentionUnavailable("fetch_not_observed")
    return json.dumps(
        {
            "schema_version": 1,
            "evaluation_id": evaluation.evaluation_id,
            "workspace_id": evaluation.workspace_id,
            "source_account_id": evaluation.member.account_id,
            "source_workspace_account_id": evaluation.workspace_account_id,
            "source_user_id": evaluation.member.user_id,
            "source_email": evaluation.member.email.strip().casefold(),
            "fetch_id": provenance.fetch_id,
            "requested_workspace_account_id": provenance.requested_workspace_account_id,
            "account_workspace_id": provenance.account_workspace_id,
            "payload_workspace_id": provenance.payload_workspace_id,
            "credential_source": provenance.credential_source,
            "started_at": _utc(provenance.started_at).isoformat().replace("+00:00", "Z"),
            "observed_at": _utc(provenance.observed_at).isoformat().replace("+00:00", "Z"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
