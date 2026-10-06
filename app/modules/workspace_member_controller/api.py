from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from app.modules.workspace_member_controller.domain import Catalog, MembershipObservation
from app.modules.workspace_member_controller.read_models import ControllerReadStatus
from app.modules.workspace_member_controller.read_service import (
    ControllerReadError,
    WorkspaceMemberControllerReadService,
)


def build_read_only_router(
    get_service: Callable[[], WorkspaceMemberControllerReadService],
    *,
    prefix: str = "/v1",
) -> APIRouter:
    """Build the standalone read surface without choosing an auth mechanism yet.

    Slice 9 owns service authentication and process packaging.  Keeping auth out
    of this factory avoids importing the Codex-LB dashboard session stack into
    the Controller core while still making the HTTP contract independently
    testable now.
    """

    router = APIRouter(prefix=prefix, tags=["workspace-member-controller"])

    @router.get("/catalog", response_model=Catalog)
    async def catalog(service: WorkspaceMemberControllerReadService = Depends(get_service)) -> Catalog:
        return await service.catalog()

    @router.get("/status", response_model=ControllerReadStatus)
    async def status(service: WorkspaceMemberControllerReadService = Depends(get_service)) -> ControllerReadStatus:
        return await service.status()

    @router.get("/workspaces/{workspace_id}/observation", response_model=MembershipObservation)
    async def observation(
        workspace_id: str,
        service: WorkspaceMemberControllerReadService = Depends(get_service),
    ) -> MembershipObservation:
        try:
            return await service.observation(workspace_id)
        except ControllerReadError as exc:
            status_code = 404 if exc.code == "workspace_not_found" else 409
            raise HTTPException(status_code=status_code, detail={"code": exc.code}) from exc

    return router
