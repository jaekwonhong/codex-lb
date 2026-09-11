from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth.dependencies import require_dashboard_write_access, validate_dashboard_session
from app.dependencies import get_member_switch_companion, get_member_switch_controls, get_member_switch_service
from app.modules.member_switch.api import handle_control_conflict, router
from app.modules.member_switch.repository import ControlConflict
from tests.unit.test_member_switch_control import context as context

pytestmark = pytest.mark.unit


def make_app(context):
    service, controls, companion, _, _ = context
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ControlConflict, handle_control_conflict)
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_write_access] = lambda: None
    app.dependency_overrides[get_member_switch_controls] = lambda: controls
    app.dependency_overrides[get_member_switch_service] = lambda: service
    app.dependency_overrides[get_member_switch_companion] = lambda: companion
    return app


async def test_routes_restore_by_id_and_never_execute_on_get(context):
    app = make_app(context)
    _, _, companion, auth, _ = context
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/member-switch-runs/active")).json() == {"run": None}
        assert companion.calls == [] and auth.calls == []
        run_id = str(uuid4())
        response = await client.post(
            "/api/member-switch-runs",
            json={
                "runId": run_id,
                "workspaceId": "cdp-1",
                "presetId": "target",
                "catalogFingerprint": "a" * 64,
            },
        )
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["phase"] == "previewed" and "previewToken" not in response.text
        before = list(companion.calls)
        for _ in range(3):
            observed = await client.get(f"/api/member-switch-runs/{run_id}")
            assert observed.json() == run
            assert observed.headers["cache-control"] == "no-store"
        assert companion.calls == before
        payload = {"commandId": str(uuid4()), "expectedRevision": run["revision"], "action": "start"}
        response = await client.post(f"/api/member-switch-runs/{run_id}/commands", json=payload)
        assert response.status_code == 200
        assert (await client.post(f"/api/member-switch-runs/{run_id}/commands", json=payload)).json() == response.json()
        assert companion.calls.count("start") == 1
        payload["commandId"] = str(uuid4())
        conflict = await client.post(f"/api/member-switch-runs/{run_id}/commands", json=payload)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "revision_conflict"
        assert (await client.get(f"/api/member-switch-runs/{uuid4()}")).status_code == 404


async def test_catalog_refresh_is_explicit_and_returns_observed_members(context):
    app = make_app(context)
    _, _, companion, _, _ = context
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        plain = await client.get("/api/member-switch-runs/catalog")
        assert plain.status_code == 200
        assert plain.json()["workspaces"][0]["currentMembers"] == []
        assert companion.calls == ["catalog"]

        refreshed = await client.post("/api/member-switch-runs/catalog/refresh")
        assert refreshed.status_code == 200, refreshed.text
        workspace = refreshed.json()["workspaces"][0]
        assert workspace["currentMembers"] == [
            {
                "email": "current@example.com",
                "userId": "user-Current",
                "presetId": None,
                "authState": "unmanaged",
                "authAccountId": None,
            }
        ]
        assert workspace["membershipCode"] == "ok"
        assert companion.calls[-4:] == ["admission", "catalog", "observe_membership:cdp-1", "catalog"]


async def test_write_access_is_required_before_control_or_companion_calls(context):
    from fastapi import HTTPException

    app = make_app(context)

    def deny():
        raise HTTPException(status_code=403, detail="read_only")

    app.dependency_overrides[require_dashboard_write_access] = deny
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/member-switch-runs/active")).status_code == 403
        assert (await client.get("/api/member-switch-runs/catalog")).status_code == 403
        assert (await client.post("/api/member-switch-runs/catalog/refresh")).status_code == 403
        assert (await client.post("/api/member-switch-runs", json={})).status_code == 403
    assert context[2].calls == [] and context[3].calls == []
