from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.responses import JSONResponse

from app.core.auth.dashboard_access import Permission
from app.core.auth.dependencies import require_dashboard_permission
from app.core.exceptions import DashboardPermissionError
from app.main import create_app
from app.modules.member_auth_handoff import api as handoff_api
from app.modules.member_auth_handoff.catalog import MemberAuthCatalogRegistrationError
from app.modules.member_auth_handoff.schemas import (
    CatalogMemberIdentity,
    CatalogMemberRegistrationRequest,
    CatalogMemberRegistrationResponse,
    MemberAuthReconciliationRequest,
    MemberAuthReconciliationResponse,
)

pytestmark = pytest.mark.unit


def test_member_auth_handoff_routes_are_registered() -> None:
    paths = set(create_app().openapi()["paths"])

    assert "/api/member-auth-handoffs" in paths
    assert "/api/member-auth-handoffs/usage" in paths
    assert "/api/member-auth-handoffs/catalog-members" in paths
    assert "/api/member-auth-handoffs/reconciliation-actions" in paths
    assert "/api/member-auth-handoffs/rotation-events/claim" in paths
    assert "/api/member-auth-handoffs/rotation-events/{event_id}/settle" in paths
    assert "/api/member-auth-handoffs/{handoff_id}" in paths


@pytest.mark.asyncio
async def test_usage_route_returns_typed_catalog_response() -> None:
    service = SimpleNamespace(
        list_catalog_member_usage=lambda: _return_value(
            {
                "members": [
                    {
                        "workspaceId": "cdp-1",
                        "presetId": "cdp-1-allnz-jk",
                        "workspaceAccountId": "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                        "email": "allnz.jk@gmail.com",
                        "userId": "user-F35N1VBxC5M3BC4LQHhamB8a",
                        "authAccountId": "local-1",
                        "authStatus": "active",
                        "availability": "available",
                        "remainingPercent": 42.0,
                        "resetAt": None,
                        "observedAt": "2026-07-24T04:05:06Z",
                    }
                ]
            }
        )
    )

    response = cast(
        dict[str, Any],
        await handoff_api.get_catalog_member_usage(
            _write_access=None,
            context=cast(Any, SimpleNamespace(service=service)),
        ),
    )

    assert response["members"][0]["remainingPercent"] == 42.0


@pytest.mark.asyncio
async def test_unknown_handoff_returns_dashboard_error() -> None:
    service = SimpleNamespace(get_status=_return_none)

    response = cast(
        JSONResponse,
        await handoff_api.get_handoff_status(
            "missing",
            _write_access=None,
            context=cast(Any, SimpleNamespace(service=service)),
        ),
    )

    assert response.status_code == 404
    assert json.loads(bytes(response.body))["error"]["code"] == "handoff_not_found"


@pytest.mark.asyncio
async def test_catalog_registration_route_returns_typed_identity() -> None:
    request = CatalogMemberRegistrationRequest(
        workspace_id="cdp-1",
        preset_id="custom-cdp-1-new-member",
        display_name="new.member",
        email="new.member@gmail.com",
        user_id="user-NewMember123",
    )
    response_value = CatalogMemberRegistrationResponse(
        accepted=True,
        code="created",
        member=CatalogMemberIdentity(
            **request.model_dump(),
            workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        ),
    )
    service = SimpleNamespace(register_catalog_member=lambda _request: response_value)

    response = await handoff_api.register_catalog_member(
        request,
        _write_access=None,
        context=cast(Any, SimpleNamespace(service=service)),
    )

    assert response == response_value


@pytest.mark.asyncio
async def test_auth_reconciliation_route_returns_typed_result() -> None:
    request = MemberAuthReconciliationRequest(
        action="cleanup_old_auth",
        workspace_id="cdp-1",
        preset_id="cdp-1-allnz-jk",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        target_email="allnz.jk@gmail.com",
        target_user_id="user-F35N1VBxC5M3BC4LQHhamB8a",
        membership_state="active",
        catalog_fingerprint="a" * 64,
    )
    expected = MemberAuthReconciliationResponse(
        accepted=True,
        code="already_clean",
        action="cleanup_old_auth",
    )
    service = SimpleNamespace(reconcile_auth=lambda _request: _return_value(expected))

    response = await handoff_api.reconcile_auth(
        request,
        _write_access=None,
        context=cast(Any, SimpleNamespace(service=service)),
    )

    assert response == expected


@pytest.mark.asyncio
async def test_catalog_registration_route_returns_bounded_dashboard_error() -> None:
    request = CatalogMemberRegistrationRequest(
        workspace_id="cdp-1",
        preset_id="custom-cdp-1-owner",
        display_name="owner",
        email="jaekwonhong14@gmail.com",
        user_id="user-Owner123",
    )

    def _reject(_request):
        raise MemberAuthCatalogRegistrationError(
            "owner_not_allowed",
            "The workspace owner cannot be registered as a member candidate.",
        )

    response = cast(
        JSONResponse,
        await handoff_api.register_catalog_member(
            request,
            _write_access=None,
            context=cast(Any, SimpleNamespace(service=SimpleNamespace(register_catalog_member=_reject))),
        ),
    )

    assert response.status_code == 409
    assert json.loads(bytes(response.body))["error"]["code"] == "owner_not_allowed"


@pytest.mark.asyncio
async def test_handoff_status_refuses_read_only_guest(app_instance, async_client) -> None:  # type: ignore[no-untyped-def]
    async def _guest_refused() -> None:
        raise DashboardPermissionError(
            "Read-only dashboard access cannot modify dashboard state",
            code="read_only_access",
        )

    accounts_write = require_dashboard_permission(Permission.ACCOUNTS_WRITE)
    app_instance.dependency_overrides[accounts_write] = _guest_refused
    try:
        response = await async_client.get("/api/member-auth-handoffs/handoff-1")
    finally:
        app_instance.dependency_overrides.pop(accounts_write, None)

    assert response.status_code == 403


async def _return_none(_handoff_id: str):
    return None


async def _return_value(value):
    return value


async def test_status_get_never_constructs_the_mutating_context():
    from unittest.mock import AsyncMock

    import httpx
    from fastapi import FastAPI

    from app.core.auth.dependencies import validate_dashboard_session
    from app.dependencies import get_member_auth_handoff_context, get_member_auth_handoff_read_context

    app = FastAPI()
    app.include_router(handoff_api.router)
    reader = SimpleNamespace(get_status=AsyncMock(return_value=None))
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_permission(Permission.ACCOUNTS_WRITE)] = lambda: None
    app.dependency_overrides[get_member_auth_handoff_read_context] = lambda: SimpleNamespace(service=reader)

    def forbidden():
        raise AssertionError("GET must not initialize OAuth, tokens, account writers or catalog registry")

    app.dependency_overrides[get_member_auth_handoff_context] = forbidden
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/member-auth-handoffs/stored-id")
    assert response.status_code == 404
    reader.get_status.assert_awaited_once_with("stored-id")
