from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.member_switch.schemas import Catalog as LegacyCatalogImport
from app.modules.workspace_member_controller.domain import (
    Catalog,
    Member,
    MembershipObservation,
    OwnerAuthTarget,
    Workspace,
)
from app.modules.workspace_member_controller.ports import MembershipObservationPort, WorkspaceCatalogPort

pytestmark = pytest.mark.unit


def test_domain_models_keep_existing_camel_case_and_utc_wire_contract():
    catalog = Catalog(
        enabled=True,
        schema_version=1,
        catalog_fingerprint="a" * 64,
        workspaces=[
            Workspace(
                id="workspace-1",
                workspace_account_id="workspace-account-1",
                workspace_name="Workspace One",
                owner_email="owner@example.com",
                members=[
                    Member(
                        preset_id="member-1",
                        display_name="Member One",
                        email="member@example.com",
                        user_id="user-Member1",
                    )
                ],
                membership_observed_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
            )
        ],
    )

    payload = catalog.model_dump(mode="json", by_alias=True)
    workspace = payload["workspaces"][0]
    assert workspace["workspaceAccountId"] == "workspace-account-1"
    assert workspace["membershipObservedAt"] == "2026-10-06T00:00:00Z"
    assert LegacyCatalogImport is Catalog


def test_owner_identity_boundary_remains_in_controller_domain():
    with pytest.raises(ValidationError, match="owner_auth_identity_mismatch"):
        Workspace(
            id="workspace-1",
            workspace_account_id="workspace-account-1",
            workspace_name="Workspace One",
            owner_email="owner@example.com",
            owner_auth=OwnerAuthTarget(
                preset_id="owner:other-workspace",
                email="owner@example.com",
                user_id="user-Owner1",
            ),
            members=[],
        )


async def test_read_ports_are_structural_and_split_catalog_from_observation():
    class CatalogReader:
        async def catalog(self) -> Catalog:
            return Catalog(enabled=True, schema_version=1, catalog_fingerprint="b" * 64, workspaces=[])

    class Observer:
        async def observe_membership(self, workspace_id: str) -> MembershipObservation:
            return MembershipObservation(
                schema_version=1,
                available=True,
                code="ok",
                workspace_id=workspace_id,
                workspace_account_id="workspace-account-1",
                catalog_fingerprint="b" * 64,
                observed_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
                complete=True,
                owner_verified=True,
                identity_ambiguous=False,
                partial_identity=False,
                duplicate_identity=False,
                unknown_member=False,
                members=[],
            )

    catalog_port: WorkspaceCatalogPort = CatalogReader()
    observation_port: MembershipObservationPort = Observer()
    assert (await catalog_port.catalog()).catalog_fingerprint == "b" * 64
    assert (await observation_port.observe_membership("workspace-1")).owner_verified is True


def test_controller_domain_and_ports_do_not_import_dashboard_proxy_or_account_modules():
    root = Path(__file__).parents[2] / "app" / "modules" / "workspace_member_controller"
    forbidden = (
        "app.modules.shared",
        "app.modules.proxy",
        "app.modules.accounts",
        "app.db.models",
        "app.dependencies",
    )
    for path in (root / "domain.py", root / "ports.py"):
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        assert not any(module.startswith(prefix) for module in imports for prefix in forbidden), (path, imports)
