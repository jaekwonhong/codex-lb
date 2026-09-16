from __future__ import annotations

from collections import defaultdict
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.utils.time import utcnow
from app.modules.member_auth_handoff.catalog import (
    PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    MemberAuthHandoffCatalogEntry,
    MemberAuthHandoffCatalogRegistry,
    resolve_catalog_workspace_label,
)
from app.modules.member_auth_handoff.repository import MemberAuthCatalogOverlayRepository
from app.modules.member_auth_handoff.rotation_events import RotationQuotaRepository
from app.modules.member_auth_handoff.usage_snapshot_repository import (
    HistoricalUsageSnapshotView,
    MemberUsageSnapshotRepository,
)
from app.modules.member_rotation_operator.adapter import (
    OperatorMemberIdentity,
    RotationOperatorSnapshot,
    RotationOperatorSnapshotAdapter,
)
from app.modules.member_rotation_operator.repository import MemberRotationOperatorRepository
from app.modules.member_rotation_operator.schemas import (
    HistoricalUsageWindowView,
    RemovedMemberHistoryView,
    RotationControllerView,
    RotationFiveHourUsageView,
    RotationFoundationView,
    RotationIntentView,
    RotationOperatorMember,
    RotationOperatorResponse,
    RotationQuotaView,
    RotationResetView,
    RotationWeeklyUsageView,
    RotationWorkspaceOperatorView,
    WeeklyState,
)

ROTATION_GUARD_24H_LIMIT = 3
ROTATION_GUARD_168H_LIMIT = 7


class RotationWorkspaceNotFound(ValueError):
    pass


def _member(identity: OperatorMemberIdentity | None) -> RotationOperatorMember | None:
    if identity is None:
        return None
    return RotationOperatorMember(
        preset_id=identity.preset_id,
        email=identity.email,
        user_id=identity.user_id,
    )


def _history_window(row: HistoricalUsageSnapshotView) -> HistoricalUsageWindowView:
    return HistoricalUsageWindowView(
        logical_window=cast(Literal["5h", "weekly"], row.logical_window),
        source_window=row.source_window,
        used_percent=row.used_percent,
        original_reset_at=row.reset_at,
        effective_reset_at=row.effective_reset_at,
        observed_at=row.observed_at,
        retained_at=row.retained_at,
        reset_schedule_invalidated=row.reset_invalidation_id is not None,
    )


class MemberRotationOperatorService:
    """Build the operator read model without performing or authorizing member effects."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        snapshot_adapter: RotationOperatorSnapshotAdapter,
    ) -> None:
        self._session = session
        self._operator_repo = MemberRotationOperatorRepository(session)
        self._quota_repo = RotationQuotaRepository(session)
        self._usage_history_repo = MemberUsageSnapshotRepository(session)
        self._snapshot_adapter = snapshot_adapter
        settings = get_settings()
        self._catalog = MemberAuthHandoffCatalogRegistry(
            MemberAuthCatalogOverlayRepository(settings.data_dir / "member-auth-handoff-catalog.json"),
            PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
        ).effective_catalog()

    def _workspace_entries(self) -> dict[str, tuple[MemberAuthHandoffCatalogEntry, ...]]:
        grouped: dict[str, list[MemberAuthHandoffCatalogEntry]] = defaultdict(list)
        for entry in self._catalog.entries:
            grouped[entry.workspace_id].append(entry)
        return {workspace_id: tuple(entries) for workspace_id, entries in grouped.items()}

    @staticmethod
    def _validated_snapshot(
        snapshot: RotationOperatorSnapshot | None,
        *,
        workspace_id: str,
        workspace_account_id: str,
    ) -> RotationOperatorSnapshot | None:
        if snapshot is None:
            return None
        if snapshot.workspace_id != workspace_id or snapshot.workspace_account_id != workspace_account_id:
            return None
        return snapshot

    @staticmethod
    def _candidate_allowed(
        candidate: OperatorMemberIdentity | None,
        entries: tuple[MemberAuthHandoffCatalogEntry, ...],
        owner_email: str,
    ) -> bool:
        if candidate is None or candidate.email.casefold() == owner_email.casefold():
            return False
        return any(
            entry.preset_id == candidate.preset_id
            and entry.email.casefold() == candidate.email.casefold()
            and entry.user_id == candidate.user_id
            for entry in entries
        )

    @staticmethod
    def _foundation(snapshot: RotationOperatorSnapshot | None) -> RotationFoundationView | None:
        foundation = None if snapshot is None else snapshot.foundation
        if foundation is None:
            return None
        return RotationFoundationView(
            state=foundation.state.value,
            admission_ready=foundation.admission_ready,
            attention_required=foundation.attention_required,
            weekly_state=cast(WeeklyState, foundation.weekly_state),
            weekly_reason=foundation.weekly_reason,
            reset_status=foundation.reset_status,
            quota_code=foundation.quota_code,
            count_24h=foundation.count_24h,
            count_168h=foundation.count_168h,
        )

    @staticmethod
    def _reset_view(snapshot: RotationOperatorSnapshot | None) -> RotationResetView:
        foundation = None if snapshot is None else snapshot.foundation
        if foundation is None:
            return RotationResetView(state="unknown", detail="controller_snapshot_unavailable")
        detail = None if snapshot is None else snapshot.reset_detail
        if (
            foundation.state.value == "reset_reconciliation_pending"
            or foundation.reset_status == "reconciliation_pending"
        ):
            return RotationResetView(state="reconciliation_pending", detail=detail)
        if foundation.state.value == "reset_recovered" or foundation.reset_status == "usage_recovered":
            return RotationResetView(state="usage_recovered", detail=detail)
        if foundation.state.value == "reset_unavailable" or foundation.reset_status == "unavailable":
            return RotationResetView(state="unavailable", detail=detail)
        if foundation.reset_status == "confirmed_no_redeemable_credit":
            return RotationResetView(state="confirmed_no_redeemable_credit", detail=detail)
        if foundation.state.value == "reset_required":
            if snapshot is not None and snapshot.reset_state == "redeem_in_progress":
                return RotationResetView(state="redeem_in_progress", detail=detail)
            return RotationResetView(state="resolution_required", detail=detail)
        return RotationResetView(state="unknown", detail=detail or "reset_resolution_not_reported")

    @staticmethod
    def _history(
        rows: list[HistoricalUsageSnapshotView],
        snapshot: RotationOperatorSnapshot | None,
    ) -> list[RemovedMemberHistoryView]:
        grouped: dict[tuple[str, str], list[HistoricalUsageSnapshotView]] = defaultdict(list)
        for row in rows:
            grouped[(row.user_id, row.membership_epoch)].append(row)
        removed_at_map = {} if snapshot is None else snapshot.removed_at_by_membership_epoch
        result: list[RemovedMemberHistoryView] = []
        for (_user_id, membership_epoch), items in grouped.items():
            ordered = sorted(items, key=lambda item: item.retained_at, reverse=True)
            newest = ordered[0]
            by_window = {item.logical_window: item for item in items}
            result.append(
                RemovedMemberHistoryView(
                    email=newest.email,
                    user_id=newest.user_id,
                    preset_id=newest.preset_id,
                    membership_epoch=membership_epoch,
                    removed_at=removed_at_map.get(membership_epoch),
                    retained_at=max(item.retained_at for item in items),
                    five_hour=_history_window(by_window["5h"]) if "5h" in by_window else None,
                    weekly=_history_window(by_window["weekly"]) if "weekly" in by_window else None,
                )
            )
        return sorted(result, key=lambda item: item.retained_at, reverse=True)

    async def read(self) -> RotationOperatorResponse:
        workspaces: list[RotationWorkspaceOperatorView] = []
        now = utcnow()
        for workspace_id, entries in sorted(self._workspace_entries().items()):
            first = entries[0]
            workspace_account_id = first.workspace_account_id
            owner_email = first.owner_email
            intent = await self._operator_repo.intent(
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
            )
            quota = await self._quota_repo.snapshot(
                workspace_account_id=workspace_account_id,
                observed_at=now,
            )
            history_rows = await self._usage_history_repo.list_history(
                workspace_account_id=workspace_account_id,
            )
            snapshot = self._validated_snapshot(
                await self._snapshot_adapter.snapshot(
                    workspace_id=workspace_id,
                    workspace_account_id=workspace_account_id,
                ),
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
            )
            effect_attention = await self._operator_repo.unresolved_effect_codes(
                workspace_account_id=workspace_account_id,
            )
            snapshot_blockers = () if snapshot is None else snapshot.blocker_codes
            blocker_codes = list(dict.fromkeys((*snapshot_blockers, *effect_attention)))
            if snapshot is not None and snapshot.companion_status == "capability_mismatch":
                blocker_codes.append("companion_capability_mismatch")
            if snapshot is not None and snapshot.companion_status == "provenance_mismatch":
                blocker_codes.append("companion_provenance_mismatch")
            if intent.enabled and snapshot is None:
                blocker_codes.append("controller_snapshot_unavailable")
            foundation = self._foundation(snapshot)
            if foundation is not None and foundation.attention_required and foundation.state not in blocker_codes:
                blocker_codes.append(foundation.state)

            candidate = None if snapshot is None else snapshot.next_candidate
            if candidate is not None and not self._candidate_allowed(candidate, entries, owner_email):
                candidate = None
                blocker_codes.append("invalid_next_candidate")

            if effect_attention:
                controller_status = "needs_attention"
                controller_reason = effect_attention[0]
            elif snapshot is not None:
                controller_status = snapshot.controller_status
                controller_reason = snapshot.controller_reason
            elif not intent.enabled:
                controller_status = "disabled"
                controller_reason = "automatic_rotation_disabled"
            else:
                controller_status = "integration_pending"
                controller_reason = "controller_snapshot_unavailable"

            weekly_state = "unknown" if foundation is None else foundation.weekly_state
            weekly_reason = "foundation_snapshot_unavailable" if foundation is None else foundation.weekly_reason
            five_hour = None if snapshot is None else snapshot.five_hour
            remove_effect = None if snapshot is None else snapshot.remove_effect
            invite_effect = None if snapshot is None else snapshot.invite_effect
            if "unknown_remove_effect" in effect_attention:
                remove_effect = "unknown"
            if "unknown_invite_effect" in effect_attention:
                invite_effect = "unknown"
            workspaces.append(
                RotationWorkspaceOperatorView(
                    workspace_id=workspace_id,
                    workspace_account_id=workspace_account_id,
                    workspace_name=resolve_catalog_workspace_label(workspace_account_id) or workspace_id,
                    owner_email=owner_email,
                    automatic_rotation_enabled=intent.enabled,
                    control_version=intent.version,
                    current_member=_member(None if snapshot is None else snapshot.current_member),
                    weekly_usage=RotationWeeklyUsageView(state=weekly_state, reason=weekly_reason),
                    five_hour_usage=RotationFiveHourUsageView(
                        state="missing" if five_hour is None else five_hour.state,
                        used_percent=None if five_hour is None else five_hour.used_percent,
                        reset_at=None if five_hour is None else five_hour.reset_at,
                        observed_at=None if five_hour is None else five_hour.observed_at,
                    ),
                    reset_credit=self._reset_view(snapshot),
                    quota=RotationQuotaView(
                        count_24h=quota.count_24h,
                        limit_24h=ROTATION_GUARD_24H_LIMIT,
                        count_168h=quota.count_168h,
                        limit_168h=ROTATION_GUARD_168H_LIMIT,
                        count_basis=quota.count_basis,
                        history_complete=quota.history_complete,
                        coverage_started_at=quota.coverage_started_at,
                    ),
                    foundation=foundation,
                    controller=RotationControllerView(
                        status=controller_status,
                        reason=controller_reason,
                        remove_effect=remove_effect,
                        invite_effect=invite_effect,
                        invitation_issued=None if snapshot is None else snapshot.invitation_issued,
                        membership_confirmed=None if snapshot is None else snapshot.membership_confirmed,
                        companion_status=None if snapshot is None else snapshot.companion_status,
                    ),
                    next_candidate=_member(candidate),
                    blocker_codes=list(dict.fromkeys(blocker_codes)),
                    history=self._history(history_rows, snapshot),
                )
            )
        return RotationOperatorResponse(workspaces=workspaces)

    async def update_intent(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        expected_version: int,
    ) -> RotationIntentView:
        entries = self._workspace_entries().get(workspace_id)
        if not entries:
            raise RotationWorkspaceNotFound(workspace_id)
        workspace_account_id = entries[0].workspace_account_id
        saved = await self._operator_repo.set_intent(
            workspace_id=workspace_id,
            workspace_account_id=workspace_account_id,
            enabled=enabled,
            expected_version=expected_version,
        )
        return RotationIntentView(
            workspace_id=saved.workspace_id,
            workspace_account_id=saved.workspace_account_id,
            enabled=saved.enabled,
            version=saved.version,
        )
