from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.auth.dependencies import (
    require_dashboard_write_access,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.errors import dashboard_error
from app.dependencies import (
    get_member_auth_enrollment_service,
    get_member_switch_companion,
    get_member_switch_controls,
    get_member_switch_service,
)
from app.modules.member_switch.admission import local_admission
from app.modules.member_switch.auth_enrollment import MemberAuthEnrollmentService
from app.modules.member_switch.companion import CompanionClient
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.schemas import (
    ActiveAuthEnrollmentResponse,
    ActiveRunResponse,
    AuthEnrollmentCommandRequest,
    AuthEnrollmentCreateRequest,
    AuthEnrollmentView,
    Catalog,
    CommandRequest,
    CreateRunRequest,
    LocalAdmission,
    RunView,
)
from app.modules.member_switch.service import MemberSwitchService


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/member-switch-runs",
    tags=["dashboard"],
    dependencies=[
        Depends(validate_dashboard_session),
        Depends(set_dashboard_error_format),
        Depends(require_dashboard_write_access),
        Depends(_no_store),
    ],
)


async def handle_control_conflict(_request: Request, error: Exception) -> JSONResponse:
    code = error.code if isinstance(error, ControlConflict) else "member_switch_failed"
    return JSONResponse(
        status_code=404 if code in {"run_not_found", "auth_enrollment_not_found"} else 409,
        content=dashboard_error(code, "The command was not replayed. Inspect the stored run before continuing."),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/catalog", response_model=Catalog)
async def catalog(companion: CompanionClient = Depends(get_member_switch_companion)) -> Catalog:
    return await companion.catalog()


@router.post("/catalog/refresh", response_model=Catalog)
async def refresh_catalog(service: MemberSwitchService = Depends(get_member_switch_service)) -> Catalog:
    return await service.refresh_catalog()


@router.get("/active", response_model=ActiveRunResponse)
async def active(controls: MemberSwitchControlRepository = Depends(get_member_switch_controls)) -> ActiveRunResponse:
    record = await controls.active()
    return ActiveRunResponse(run=None if record is None or record.kind != "run" else MemberSwitchService._view(record))


@router.get("/admission", response_model=LocalAdmission)
async def admission(controls: MemberSwitchControlRepository = Depends(get_member_switch_controls)) -> LocalAdmission:
    return await local_admission(controls)


@router.get("/oauth-enrollments/active", response_model=ActiveAuthEnrollmentResponse)
async def active_auth_enrollment(
    service: MemberAuthEnrollmentService = Depends(get_member_auth_enrollment_service),
) -> ActiveAuthEnrollmentResponse:
    return ActiveAuthEnrollmentResponse(enrollment=await service.active())


@router.post("/oauth-enrollments/auto", response_model=AuthEnrollmentView)
async def auto_auth_enrollment(
    request: AuthEnrollmentCreateRequest,
    service: MemberAuthEnrollmentService = Depends(get_member_auth_enrollment_service),
) -> AuthEnrollmentView:
    return await service.create_and_auto_complete(request)


@router.post("/oauth-enrollments/{enrollment_id}/auto", response_model=AuthEnrollmentView)
async def resume_auto_auth_enrollment(
    enrollment_id: UUID,
    service: MemberAuthEnrollmentService = Depends(get_member_auth_enrollment_service),
) -> AuthEnrollmentView:
    return await service.auto_complete(str(enrollment_id), allow_manual_resume=True)


@router.get("/oauth-enrollments/{enrollment_id}", response_model=AuthEnrollmentView)
async def get_auth_enrollment(
    enrollment_id: UUID,
    service: MemberAuthEnrollmentService = Depends(get_member_auth_enrollment_service),
) -> AuthEnrollmentView:
    enrollment = await service.get(str(enrollment_id))
    if enrollment is None:
        raise ControlConflict("auth_enrollment_not_found")
    return enrollment


@router.post("/oauth-enrollments", response_model=AuthEnrollmentView)
async def create_auth_enrollment(
    request: AuthEnrollmentCreateRequest,
    service: MemberAuthEnrollmentService = Depends(get_member_auth_enrollment_service),
) -> AuthEnrollmentView:
    return await service.create(request)


@router.post("/oauth-enrollments/{enrollment_id}/commands", response_model=AuthEnrollmentView)
async def auth_enrollment_command(
    enrollment_id: UUID,
    request: AuthEnrollmentCommandRequest,
    service: MemberAuthEnrollmentService = Depends(get_member_auth_enrollment_service),
) -> AuthEnrollmentView:
    return await service.command(str(enrollment_id), request)


@router.get("/{run_id}", response_model=RunView)
async def get_run(
    run_id: UUID, controls: MemberSwitchControlRepository = Depends(get_member_switch_controls)
) -> RunView:
    record = await controls.get(str(run_id))
    if record is None or record.kind != "run":
        raise ControlConflict("run_not_found")
    return MemberSwitchService._view(record)


@router.post("", response_model=RunView)
async def create_run(
    request: CreateRunRequest, service: MemberSwitchService = Depends(get_member_switch_service)
) -> RunView:
    return await service.create(request)


@router.post("/{run_id}/commands", response_model=RunView)
async def command(
    run_id: UUID, request: CommandRequest, service: MemberSwitchService = Depends(get_member_switch_service)
) -> RunView:
    return await service.command(str(run_id), request)
