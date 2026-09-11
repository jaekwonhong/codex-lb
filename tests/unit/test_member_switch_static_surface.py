from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[2]
FEATURE = ROOT / "frontend/src/features/member-switch"


def test_frontend_keeps_only_the_server_owned_manual_contract() -> None:
    retired = {
        "client.ts",
        "schemas.ts",
        "ranking.ts",
        "reconciliation.ts",
        "rotation-policy.ts",
    }
    assert not any((FEATURE / name).exists() for name in retired)

    production = [path for path in FEATURE.rglob("*.ts*") if ".test." not in path.name]
    source = "\n".join(path.read_text(encoding="utf-8") for path in production)
    assert "/api/member-switch-runs" in source
    for retired_path in (
        "/cleanup-operations",
        "/recovery-operations",
        "/session-readiness",
        "/oauth-browser/operations",
        "/workspace-account-resolutions",
        "/reconciliation-actions",
    ):
        assert retired_path not in source


def test_companion_production_route_surface_does_not_map_retired_mutations() -> None:
    endpoints = (ROOT.parent / "companion/Hosting/MemberSwitchEndpoints.cs").read_text(encoding="utf-8")
    for retired_path in (
        "cleanup-operations",
        "recovery-operations",
        "session-readiness",
        "oauth-browser/operations",
        "workspace-account-resolutions",
        "automatic-rotation",
    ):
        assert retired_path not in endpoints
