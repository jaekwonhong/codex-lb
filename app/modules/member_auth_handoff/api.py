from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.auth.dashboard_access import Permission
from app.core.auth.dependencies import (
    require_dashboard_permission,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.errors import dashboard_error
from app.dependencies import (
    MemberAuthHandoffContext,
    MemberAuthHandoffReadContext,
    get_member_auth_handoff_context,
    get_member_auth_handoff_read_context,
)
from app.modules.member_auth_handoff.catalog import MemberAuthCatalogRegistrationError
from app.modules.member_auth_handoff.rotation_events import claim_pending_event, settle_event
from app.modules.member_auth_handoff.schemas import (
    CatalogMemberRegistrationRequest,
    CatalogMemberRegistrationResponse,
    CatalogMemberUsageResponse,
    MemberAuthHandoffPrepareRequest,
    MemberAuthHandoffResponse,
    MemberAuthReconciliationRequest,
    MemberAuthReconciliationResponse,
    MemberRotationEvent,
    MemberRotationEventClaimResponse,
    MemberRotationEventSettleRequest,
    MemberRotationEventSettleResponse,
    WorkspaceAuthObservationResponse,
)
from app.modules.member_switch.repository import ControlConflict


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _reject_legacy_mutation(
    request: Request,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        raise ControlConflict("managed_run_command_required")


router = APIRouter(
    prefix="/api/member-auth-handoffs",
    tags=["dashboard"],
    dependencies=[
        Depends(validate_dashboard_session),
        Depends(set_dashboard_error_format),
        Depends(_no_store),
        Depends(_reject_legacy_mutation),
    ],
)


@router.post("/rotation-events/claim", response_model=MemberRotationEventClaimResponse)
async def claim_rotation_event(
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
) -> MemberRotationEventClaimResponse:
    event = await claim_pending_event()
    return MemberRotationEventClaimResponse(
        claimed=event is not None,
        event=MemberRotationEvent.model_validate(asdict(event)) if event is not None else None,
    )


@router.post(
    "/rotation-events/{event_id}/settle",
    response_model=MemberRotationEventSettleResponse,
)
async def settle_rotation_event(
    event_id: str,
    request: MemberRotationEventSettleRequest,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
) -> MemberRotationEventSettleResponse:
    return MemberRotationEventSettleResponse(
        accepted=await settle_event(
            event_id,
            request.claim_token,
            processed=request.processed,
        )
    )


@router.post("", response_model=MemberAuthHandoffResponse)
async def prepare_handoff(
    request: MemberAuthHandoffPrepareRequest,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
    context: MemberAuthHandoffContext = Depends(get_member_auth_handoff_context),
) -> MemberAuthHandoffResponse:
    return await context.service.prepare(request)


@router.get("/usage", response_model=CatalogMemberUsageResponse)
async def get_catalog_member_usage(
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
    context: MemberAuthHandoffContext = Depends(get_member_auth_handoff_context),
) -> CatalogMemberUsageResponse:
    return await context.service.list_catalog_member_usage()


@router.get("/workspaces/{workspace_id}/observation", response_model=WorkspaceAuthObservationResponse)
async def get_workspace_auth_observation(
    workspace_id: str,
    workspace_account_id: str,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
    context: MemberAuthHandoffContext = Depends(get_member_auth_handoff_context),
) -> WorkspaceAuthObservationResponse:
    return await context.service.observe_workspace_auth(
        workspace_id=workspace_id,
        workspace_account_id=workspace_account_id,
    )


@router.post("/reconciliation-actions", response_model=MemberAuthReconciliationResponse)
async def reconcile_auth(
    request: MemberAuthReconciliationRequest,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
    context: MemberAuthHandoffContext = Depends(get_member_auth_handoff_context),
) -> MemberAuthReconciliationResponse:
    return await context.service.reconcile_auth(request)


@router.post("/catalog-members", response_model=CatalogMemberRegistrationResponse)
async def register_catalog_member(
    request: CatalogMemberRegistrationRequest,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
    context: MemberAuthHandoffContext = Depends(get_member_auth_handoff_context),
) -> CatalogMemberRegistrationResponse | JSONResponse:
    try:
        return context.service.register_catalog_member(request)
    except MemberAuthCatalogRegistrationError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=dashboard_error(exc.code, str(exc)),
        )


@router.get("/{handoff_id}", response_model=MemberAuthHandoffResponse)
async def get_handoff_status(
    handoff_id: str,
    _write_access=Depends(require_dashboard_permission(Permission.ACCOUNTS_WRITE)),
    context: MemberAuthHandoffReadContext = Depends(get_member_auth_handoff_read_context),
) -> MemberAuthHandoffResponse | JSONResponse:
    response = await context.service.get_status(handoff_id)
    if response is None:
        return JSONResponse(
            status_code=404,
            content=dashboard_error("handoff_not_found", "Member auth handoff was not found."),
        )
    return response
