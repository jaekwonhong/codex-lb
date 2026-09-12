from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.accounts.schemas import AccountProbeResponse
from app.modules.member_switch.post_probe import MemberAuthPostProbeService

pytestmark = pytest.mark.unit


async def test_post_probe_exposes_successful_usage_refresh_even_when_probe_request_is_rejected(monkeypatch):
    result = AccountProbeResponse(
        status="probed",
        account_id="account-1",
        probe_status_code=400,
        primary_used_percent_before=None,
        primary_used_percent_after=0.0,
        secondary_used_percent_before=None,
        secondary_used_percent_after=0.0,
        account_status_before="active",
        account_status_after="active",
    )
    result._usage_refresh_fetch_succeeded = True
    accounts = SimpleNamespace(probe_account=AsyncMock(return_value=result))
    settlement = SimpleNamespace(record_account_probe_result=AsyncMock())
    monkeypatch.setattr("app.modules.accounts.probe.AuditService.log_async", lambda *_args, **_kwargs: None)
    service = MemberAuthPostProbeService(accounts, settlement)

    diagnostic = await service.probe("account-1")

    assert diagnostic.state == "completed"
    assert diagnostic.probe_status_code == 400
    assert diagnostic.primary_used_percent_after == 0.0
    assert diagnostic.account_status_after == "active"
    assert diagnostic.usage_refresh_succeeded is True
    settlement.record_account_probe_result.assert_awaited_once_with(account_id="account-1", http_status=400)
