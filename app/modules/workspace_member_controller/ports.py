from __future__ import annotations

from typing import Protocol

from app.modules.workspace_member_controller.domain import Catalog, MembershipObservation


class WorkspaceCatalogPort(Protocol):
    """Read the authoritative workspace/member catalog snapshot."""

    async def catalog(self) -> Catalog: ...


class MembershipObservationPort(Protocol):
    """Observe current owner/member state for one exact workspace."""

    async def observe_membership(self, workspace_id: str) -> MembershipObservation: ...


class WorkspaceReadPort(WorkspaceCatalogPort, MembershipObservationPort, Protocol):
    """Read-only boundary needed by Controller catalog/observation workflows."""

