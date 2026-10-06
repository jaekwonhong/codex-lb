from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.member_auth_handoff.rotation_events import RotationQuotaRepository
from app.modules.workspace_member_controller.rotation_decision import (
    MembershipMutationBudgetDecision,
    MembershipMutationBudgetPort,
)


class LegacyMembershipMutationBudget(MembershipMutationBudgetPort):
    """Compatibility adapter over the Controller-owned rolling mutation quota table."""

    def __init__(
        self,
        sessions: Callable[[], AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock

    async def reserve(
        self,
        *,
        operation_id: str,
        evaluation_id: str,
        workspace_id: str,
        workspace_account_id: str,
    ) -> MembershipMutationBudgetDecision:
        async with self._sessions() as session:
            decision = await RotationQuotaRepository(session, clock=self._clock).reserve(
                operation_id=operation_id,
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                rotation_event_id=evaluation_id,
            )
        return MembershipMutationBudgetDecision(
            admitted=decision.admitted,
            code=decision.code,
            count_24h=decision.count_24h,
            count_168h=decision.count_168h,
            coverage_started_at=decision.coverage_started_at,
        )
