from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException

from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationCommand,
    MembershipMutationView,
)
from app.modules.workspace_member_controller.mutation_service import (
    MembershipMutationError,
    WorkspaceMembershipMutationService,
)


def build_mutation_router(
    get_service: Callable[[], WorkspaceMembershipMutationService],
    *,
    prefix: str = "/v1",
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["workspace-member-controller"])

    def raise_http(exc: MembershipMutationError) -> NoReturn:
        status_code = 404 if exc.code == "mutation_operation_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code}) from exc

    @router.post("/mutations", response_model=MembershipMutationView)
    async def submit(
        command: MembershipMutationCommand,
        service: WorkspaceMembershipMutationService = Depends(get_service),
    ) -> MembershipMutationView:
        if command.mutation.action != "switch":
            raise HTTPException(status_code=409, detail={"code": "mutation_action_not_qualified"})
        try:
            return await service.submit(command)
        except MembershipMutationError as exc:
            raise_http(exc)

    @router.get("/mutations/{operation_id}", response_model=MembershipMutationView)
    async def get(
        operation_id: str,
        service: WorkspaceMembershipMutationService = Depends(get_service),
    ) -> MembershipMutationView:
        result = await service.get(operation_id)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "mutation_operation_not_found"})
        return result

    @router.post("/mutations/{operation_id}/reconcile", response_model=MembershipMutationView)
    async def reconcile(
        operation_id: str,
        service: WorkspaceMembershipMutationService = Depends(get_service),
    ) -> MembershipMutationView:
        try:
            return await service.reconcile(operation_id)
        except MembershipMutationError as exc:
            raise_http(exc)

    return router
