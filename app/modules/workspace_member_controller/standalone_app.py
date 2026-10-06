from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.modules.workspace_member_controller.api import build_read_only_router
from app.modules.workspace_member_controller.standalone_runtime import ControllerStandaloneRuntime
from app.modules.workspace_member_controller.standalone_settings import StandaloneSettings

_bearer = HTTPBearer(auto_error=False)


def create_standalone_app(
    settings: StandaloneSettings | None = None,
    runtime: ControllerStandaloneRuntime | None = None,
) -> FastAPI:
    settings = settings or StandaloneSettings()
    runtime = runtime or ControllerStandaloneRuntime.build(settings)
    admin_token = settings.resolved_admin_token()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await runtime.startup()
            yield
        finally:
            await runtime.close()

    app = FastAPI(
        title="Workspace Member Controller",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    async def require_admin(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.casefold() != "bearer"
            or not secrets.compare_digest(credentials.credentials, admin_token)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "controller_admin_unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, object]:
        return {"status": "ok", "service": "workspace-member-controller"}

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> dict[str, object]:
        try:
            report = await runtime.readiness()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "controller_not_ready"},
            ) from None
        return {
            "status": "ready",
            "workspaceCount": report.workspace_count,
            "bindingCount": report.binding_count,
            "openCodexAccountCount": report.opencodex_account_count,
        }

    app.include_router(
        build_read_only_router(lambda: runtime.read_service),
        dependencies=[Depends(require_admin)],
    )
    return app


def create_standalone_app_from_env() -> FastAPI:
    return create_standalone_app()
