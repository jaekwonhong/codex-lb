from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dashboard_access import Permission
from app.core.auth.dependencies import (
    require_dashboard_permission,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.config.settings import get_settings
from app.core.exceptions import DashboardConflictError, DashboardNotFoundError
from app.db.session import get_session
from app.modules.member_rotation_operator.adapter import get_rotation_operator_snapshot_adapter
from app.modules.member_rotation_operator.repository import RotationIntentConflict
from app.modules.member_rotation_operator.schemas import (
    RotationIntentUpdateRequest,
    RotationIntentView,
    RotationOperatorResponse,
)
from app.modules.member_rotation_operator.service import MemberRotationOperatorService, RotationWorkspaceNotFound


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/member-rotation/operator",
    tags=["dashboard"],
    dependencies=[
        Depends(validate_dashboard_session),
        Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
        Depends(set_dashboard_error_format),
        Depends(_no_store),
    ],
)


def get_member_rotation_operator_service(
    session: AsyncSession = Depends(get_session),
) -> MemberRotationOperatorService:
    return MemberRotationOperatorService(
        session,
        snapshot_adapter=get_rotation_operator_snapshot_adapter(),
    )


@router.get("", response_model=RotationOperatorResponse)
async def read_operator_status(
    service: MemberRotationOperatorService = Depends(get_member_rotation_operator_service),
) -> RotationOperatorResponse:
    return await service.read()


@router.put("/workspaces/{workspace_id}/intent", response_model=RotationIntentView)
async def update_operator_intent(
    workspace_id: str,
    payload: RotationIntentUpdateRequest,
    service: MemberRotationOperatorService = Depends(get_member_rotation_operator_service),
) -> RotationIntentView:
    if get_settings().workspace_membership_writer != "legacy":
        raise DashboardConflictError(
            "Workspace membership writes are owned by the standalone Controller",
            code="workspace_membership_writer_moved",
        )
    try:
        return await service.update_intent(
            workspace_id=workspace_id,
            enabled=payload.enabled,
            expected_version=payload.expected_version,
        )
    except RotationWorkspaceNotFound as exc:
        raise DashboardNotFoundError("Rotation workspace not found", code="rotation_workspace_not_found") from exc
    except RotationIntentConflict as exc:
        raise DashboardConflictError(str(exc), code="rotation_intent_conflict") from exc
