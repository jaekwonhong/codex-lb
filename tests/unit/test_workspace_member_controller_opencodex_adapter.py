from __future__ import annotations

import json

import httpx
import pytest

from app.modules.workspace_member_controller.account_state import (
    OpenCodexAccountNotFound,
    OpenCodexAccountStateError,
)
from app.modules.workspace_member_controller.opencodex_adapter import OpenCodexHttpAccountStateAdapter

pytestmark = pytest.mark.unit


def payload(**overrides):
    base = {
        "schemaVersion": 1,
        "provider": "openai",
        "accountId": "acct-1",
        "isMain": False,
        "selector": "member1",
        "credentialGeneration": 7,
        "observedAt": 1_000_000,
        "hasCredential": True,
        "needsReauth": False,
        "paused": False,
        "healthStatus": "healthy",
        "selectionState": "selectable",
        "exclusionReasons": [],
        "quotaState": "available",
        "quotaObservedAt": 999_000,
        "quotaWindows": [{"name": "weekly", "usedPercent": 25.0, "observedAt": 999_000}],
        "cooldowns": [],
        "stateRevision": "a" * 64,
    }
    base.update(overrides)
    return base


async def test_adapter_reads_exact_account_with_admin_bearer_and_no_secret_in_payload():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["account_id"] = request.url.params.get("accountId")
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenCodexHttpAccountStateAdapter(
            base_url="http://127.0.0.1:10101",
            admin_token="ocx_admin_test-secret",
            client=client,
        )
        state = await adapter.get("acct-1")

    assert seen == {"authorization": "Bearer ocx_admin_test-secret", "account_id": "acct-1"}
    assert state.account_id == "acct-1"
    assert state.credential_generation == 7
    assert state.is_fresh(now_ms=1_005_000, max_age_ms=10_000)
    assert state.quota_is_fresh(now_ms=1_005_000, max_age_ms=10_000)
    assert "ocx_admin_test-secret" not in json.dumps(state.model_dump(mode="json"))


async def test_adapter_fails_closed_on_identity_mismatch_and_invalid_projection():
    async def wrong_identity(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload(accountId="acct-other"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(wrong_identity)) as client:
        adapter = OpenCodexHttpAccountStateAdapter(base_url="http://ocx", admin_token="token", client=client)
        with pytest.raises(OpenCodexAccountStateError, match="opencodex_account_identity_mismatch"):
            await adapter.get("acct-1")

    async def missing_generation(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload(isMain=True, accountId="__main__", credentialGeneration=7))

    async with httpx.AsyncClient(transport=httpx.MockTransport(missing_generation)) as client:
        adapter = OpenCodexHttpAccountStateAdapter(base_url="http://ocx", admin_token="token", client=client)
        with pytest.raises(OpenCodexAccountStateError, match="opencodex_account_state_invalid"):
            await adapter.get("__main__")


async def test_adapter_maps_not_found_and_auth_failure_without_retrying_another_account():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("accountId"))
        return httpx.Response(404, json={"error": "Account not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenCodexHttpAccountStateAdapter(base_url="http://ocx", admin_token="token", client=client)
        with pytest.raises(OpenCodexAccountNotFound):
            await adapter.get("acct-missing")
    assert calls == ["acct-missing"]


def test_freshness_helpers_fail_closed_for_future_stale_and_unknown_quota():
    from app.modules.workspace_member_controller.account_state import OpenCodexAccountState

    state = OpenCodexAccountState.model_validate(payload(quotaState="unknown", quotaObservedAt=None))
    assert not state.is_fresh(now_ms=999_000, max_age_ms=10_000)
    assert not state.is_fresh(now_ms=1_020_001, max_age_ms=20_000)
    assert not state.quota_is_fresh(now_ms=1_005_000, max_age_ms=10_000)
