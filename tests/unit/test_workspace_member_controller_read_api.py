from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.modules.workspace_member_controller.api import build_read_only_router
from app.modules.workspace_member_controller.domain import Catalog, MembershipObservation, Workspace
from app.modules.workspace_member_controller.persistence import (
    MembershipOperationJournalRecord,
    WorkspaceIntentRecord,
)
from app.modules.workspace_member_controller.read_service import WorkspaceMemberControllerReadService

pytestmark = pytest.mark.unit


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def catalog() -> Catalog:
    return Catalog(
        enabled=True,
        schema_version=1,
        catalog_fingerprint="c" * 64,
        workspaces=[
            Workspace(
                id="workspace-1",
                workspace_account_id="workspace-account-1",
                workspace_name="Workspace One",
                owner_email="owner@example.com",
                members=[],
                membership_code="observed",
                membership_observed_at=NOW,
            )
        ],
    )


class Reads:
    async def catalog(self) -> Catalog:
        return catalog()

    async def observe_membership(self, workspace_id: str) -> MembershipObservation:
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id=workspace_id,
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="c" * 64,
            observed_at=NOW,
            complete=True,
            owner_verified=True,
            identity_ambiguous=False,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=[],
        )


class Intents:
    async def get(self, *, workspace_id: str, workspace_account_id: str) -> WorkspaceIntentRecord:
        return WorkspaceIntentRecord(workspace_id, workspace_account_id, True, 4, NOW)


class Operations:
    async def active(self) -> MembershipOperationJournalRecord | None:
        return MembershipOperationJournalRecord("run-1", "run", "member-switch", 7, "remove_member", "cmd-1")

    async def get(self, operation_id: str) -> MembershipOperationJournalRecord | None:
        return await self.active() if operation_id == "run-1" else None


def service() -> WorkspaceMemberControllerReadService:
    return WorkspaceMemberControllerReadService(Reads(), Intents(), Operations())


async def test_read_only_api_exposes_catalog_status_and_exact_observation():
    app = FastAPI()
    app.include_router(build_read_only_router(service))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        catalog_response = await client.get("/v1/catalog")
        status_response = await client.get("/v1/status")
        observation_response = await client.get("/v1/workspaces/workspace-1/observation")

    assert catalog_response.status_code == 200
    assert catalog_response.json()["workspaces"][0]["workspaceAccountId"] == "workspace-account-1"
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["activeOperation"] == {
        "operationId": "run-1",
        "kind": "run",
        "revision": 7,
        "pendingAction": "remove_member",
        "commandId": "cmd-1",
    }
    assert status["workspaces"][0]["intent"]["version"] == 4
    assert observation_response.status_code == 200
    assert observation_response.json()["ownerVerified"] is True


async def test_observation_identity_mismatch_fails_closed():
    class WrongReads(Reads):
        async def observe_membership(self, workspace_id: str) -> MembershipObservation:
            value = await super().observe_membership(workspace_id)
            return value.model_copy(update={"workspace_account_id": "wrong-account"})

    read_service = WorkspaceMemberControllerReadService(WrongReads(), Intents(), Operations())
    app = FastAPI()
    app.include_router(build_read_only_router(lambda: read_service))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/workspaces/workspace-1/observation")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "membership_observation_account_mismatch"


def test_router_has_no_mutation_methods():
    router = build_read_only_router(service)
    methods = {method for route in router.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}


def test_controller_persistence_and_read_core_avoid_db_proxy_and_dashboard_imports():
    root = Path(__file__).parents[2] / "app" / "modules" / "workspace_member_controller"
    forbidden = (
        "app.db.models",
        "app.modules.proxy",
        "app.modules.accounts",
        "app.modules.shared",
        "app.dependencies",
    )
    for name in ("persistence.py", "read_models.py", "read_service.py", "api.py"):
        path = root / name
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        assert not any(module.startswith(prefix) for module in imports for prefix in forbidden), (name, imports)
