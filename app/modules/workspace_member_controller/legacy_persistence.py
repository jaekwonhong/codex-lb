from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.member_rotation_operator.repository import MemberRotationOperatorRepository
from app.modules.member_switch.repository import MemberSwitchControlRepository
from app.modules.workspace_member_controller.persistence import (
    MembershipOperationJournalReader,
    MembershipOperationJournalRecord,
    WorkspaceIntentReader,
    WorkspaceIntentRecord,
)


class LegacyWorkspaceIntentReader(WorkspaceIntentReader):
    """Compatibility adapter over the existing durable workspace-control table."""

    def __init__(self, sessions: Callable[[], AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, *, workspace_id: str, workspace_account_id: str) -> WorkspaceIntentRecord:
        async with self._sessions() as session:
            record = await MemberRotationOperatorRepository(session).intent(
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
            )
        return WorkspaceIntentRecord(
            workspace_id=record.workspace_id,
            workspace_account_id=record.workspace_account_id,
            enabled=record.enabled,
            version=record.version,
            updated_at=record.updated_at,
        )


class LegacyMembershipOperationJournalReader(MembershipOperationJournalReader):
    """Read-only adapter over the existing member-switch control journal."""

    def __init__(self, controls: MemberSwitchControlRepository) -> None:
        self._controls = controls

    @staticmethod
    def _convert(record) -> MembershipOperationJournalRecord:
        return MembershipOperationJournalRecord(
            operation_id=record.id,
            kind=record.kind,
            active_scope=record.active_scope,
            revision=record.revision,
            pending_action=record.pending_action,
            command_id=record.command_id,
        )

    async def active(self) -> MembershipOperationJournalRecord | None:
        record = await self._controls.active()
        return None if record is None else self._convert(record)

    async def get(self, operation_id: str) -> MembershipOperationJournalRecord | None:
        record = await self._controls.get(operation_id)
        return None if record is None else self._convert(record)

