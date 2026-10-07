from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.core.exceptions import DashboardConflictError
from app.modules.member_rotation_operator.api import update_operator_intent
from app.modules.member_rotation_operator.schemas import RotationIntentUpdateRequest
from app.modules.member_rotation_operator.service import MemberRotationOperatorService

pytestmark = pytest.mark.unit


class UnexpectedService:
    async def update_intent(self, **_kwargs):
        pytest.fail("legacy rotation intent service must not be called in WMC writer mode")


async def test_wmc_writer_mode_fences_legacy_rotation_intent(monkeypatch):
    monkeypatch.setattr(
        "app.modules.member_rotation_operator.api.get_settings",
        lambda: SimpleNamespace(workspace_membership_writer="wmc"),
    )

    with pytest.raises(DashboardConflictError) as exc:
        await update_operator_intent(
            "workspace-1",
            RotationIntentUpdateRequest(enabled=True, expected_version=0),
            cast(MemberRotationOperatorService, UnexpectedService()),
        )

    assert exc.value.code == "workspace_membership_writer_moved"
