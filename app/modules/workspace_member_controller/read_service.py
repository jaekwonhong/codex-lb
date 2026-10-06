from __future__ import annotations

from app.modules.workspace_member_controller.domain import Catalog, MembershipObservation, Workspace
from app.modules.workspace_member_controller.persistence import (
    MembershipOperationJournalReader,
    WorkspaceIntentReader,
)
from app.modules.workspace_member_controller.ports import WorkspaceReadPort
from app.modules.workspace_member_controller.read_models import (
    ActiveMembershipOperationView,
    ControllerReadStatus,
    WorkspaceIntentView,
    WorkspaceReadStatus,
)


class ControllerReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkspaceMemberControllerReadService:
    def __init__(
        self,
        workspace_reads: WorkspaceReadPort,
        intents: WorkspaceIntentReader,
        operations: MembershipOperationJournalReader,
    ) -> None:
        self._workspace_reads = workspace_reads
        self._intents = intents
        self._operations = operations

    async def catalog(self) -> Catalog:
        return await self._workspace_reads.catalog()

    async def observation(self, workspace_id: str) -> MembershipObservation:
        catalog = await self.catalog()
        workspace = self._workspace(catalog, workspace_id)
        observed = await self._workspace_reads.observe_membership(workspace_id)
        if observed.workspace_id != workspace.id:
            raise ControllerReadError("membership_observation_workspace_mismatch")
        if observed.workspace_account_id != workspace.workspace_account_id:
            raise ControllerReadError("membership_observation_account_mismatch")
        if observed.catalog_fingerprint != catalog.catalog_fingerprint:
            raise ControllerReadError("membership_observation_catalog_mismatch")
        return observed

    async def status(self) -> ControllerReadStatus:
        catalog = await self.catalog()
        active = await self._operations.active()
        workspaces: list[WorkspaceReadStatus] = []
        for workspace in catalog.workspaces:
            intent = await self._intents.get(
                workspace_id=workspace.id,
                workspace_account_id=workspace.workspace_account_id,
            )
            if intent.workspace_id != workspace.id or intent.workspace_account_id != workspace.workspace_account_id:
                raise ControllerReadError("workspace_intent_identity_mismatch")
            workspaces.append(
                WorkspaceReadStatus(
                    workspace_id=workspace.id,
                    workspace_account_id=workspace.workspace_account_id,
                    workspace_name=workspace.workspace_name,
                    owner_email=workspace.owner_email,
                    membership_code=workspace.membership_code,
                    membership_observed_at=workspace.membership_observed_at,
                    intent=WorkspaceIntentView(
                        workspace_id=intent.workspace_id,
                        workspace_account_id=intent.workspace_account_id,
                        enabled=intent.enabled,
                        version=intent.version,
                        updated_at=intent.updated_at,
                    ),
                )
            )
        return ControllerReadStatus(
            catalog_fingerprint=catalog.catalog_fingerprint,
            enabled=catalog.enabled,
            active_operation=None
            if active is None
            else ActiveMembershipOperationView(
                operation_id=active.operation_id,
                kind=active.kind,
                revision=active.revision,
                pending_action=active.pending_action,
                command_id=active.command_id,
            ),
            workspaces=workspaces,
        )

    @staticmethod
    def _workspace(catalog: Catalog, workspace_id: str) -> Workspace:
        matches = [workspace for workspace in catalog.workspaces if workspace.id == workspace_id]
        if len(matches) != 1:
            raise ControllerReadError("workspace_not_found" if not matches else "workspace_identity_ambiguous")
        return matches[0]

