from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import app.modules.workspace_member_controller.legacy_rotation_budget as legacy
from app.modules.workspace_member_controller.legacy_rotation_budget import LegacyMembershipMutationBudget

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)


@dataclass
class Decision:
    admitted: bool = True
    code: str = "admitted"
    count_24h: int = 2
    count_168h: int = 5
    coverage_started_at: datetime = NOW


async def test_legacy_rotation_budget_maps_controller_owned_quota_without_account_inputs(monkeypatch):
    calls = []

    class Repository:
        def __init__(self, _session, *, clock=None):
            calls.append(("init", clock))

        async def reserve(self, **kwargs):
            calls.append(("reserve", kwargs))
            return Decision()

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(legacy, "RotationQuotaRepository", Repository)
    budget = LegacyMembershipMutationBudget(sessions, clock=lambda: NOW)
    result = await budget.reserve(
        operation_id="budget-1",
        evaluation_id="evaluation-1",
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
    )

    assert result.admitted is True
    assert result.count_24h == 2
    assert result.count_168h == 5
    assert calls[1] == (
        "reserve",
        {
            "operation_id": "budget-1",
            "workspace_id": "workspace-1",
            "workspace_account_id": "workspace-account-1",
            "rotation_event_id": "evaluation-1",
        },
    )
