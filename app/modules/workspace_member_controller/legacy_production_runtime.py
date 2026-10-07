from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.member_switch.companion import CompanionClient
from app.modules.member_switch.repository import MemberSwitchControlRepository
from app.modules.workspace_member_controller.legacy_companion_canary_effect import (
    LegacyCompanionProductionSwitchEffect,
)
from app.modules.workspace_member_controller.legacy_mutation_journal import (
    LegacyMembershipMutationJournal,
)
from app.modules.workspace_member_controller.mutation_admission import (
    WorkspaceMembershipMutationAdmission,
)
from app.modules.workspace_member_controller.mutation_service import (
    WorkspaceMembershipMutationService,
)
from app.modules.workspace_member_controller.ports import WorkspaceReadPort
from app.modules.workspace_member_controller.standalone_settings import StandaloneSettings


def build_legacy_production_mutation_service(
    *,
    settings: StandaloneSettings,
    sessions: Callable[[], AsyncSession],
    reads: WorkspaceReadPort,
) -> WorkspaceMembershipMutationService:
    """Migration-only writer assembly over the shared durable member-switch journal."""

    companion_url = settings.companion_base_url.rstrip("/") + "/account-pool"
    return WorkspaceMembershipMutationService(
        LegacyMembershipMutationJournal(MemberSwitchControlRepository(sessions)),
        WorkspaceMembershipMutationAdmission(reads),
        LegacyCompanionProductionSwitchEffect(CompanionClient(companion_url)),
    )
