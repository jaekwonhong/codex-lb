from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, update

import app.modules.proxy.service as proxy_module
from app.core.balancer.recovery import OwnerRecoveryHint
from app.core.clients.proxy import ProxyResponseError
from app.core.utils.time import to_utc_naive, utcnow
from app.db.models import Account, AccountStatus, HttpBridgeSessionState, RequestLog, UsageHistory
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.api_keys.service import ApiKeyUsageReservationData
from app.modules.proxy import api as proxy_api
from app.modules.proxy._service.http_bridge import streaming as bridge_streaming
from app.modules.proxy._service.http_bridge.helpers import _local_history_recovery_required_error
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.proxy.durable_bridge_coordinator import DurableBridgeLookup
from app.modules.proxy.durable_bridge_runtime import http_bridge_owner_process_epoch
from app.modules.proxy.owner_recovery import OwnerRecoveryAdvice
from tests.integration.test_http_responses_bridge import (
    _cleanup_http_bridge_sessions,  # noqa: F401 -- reuse cancellation-safe test teardown
    _collect_sse_events,
    _FakeBridgeUpstreamWebSocket,
    _get_account,
    _import_account,
    _install_bridge_settings,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity_headers", "expected_status", "expected_code", "admission_case"),
    [
        ({"user-agent": "Codex Desktop/0.159.2 (Windows; x86_64)"}, 400, "continuity_recovery_required", "early"),
        ({"user-agent": "test-client", "originator": "codex_cli_rs"}, 400, "continuity_recovery_required", "early"),
        ({"originator": "codex_cli_rs"}, 400, "continuity_recovery_required", "early"),
        ({"user-agent": "openai-python/2.0"}, 502, "previous_response_owner_unavailable", "early"),
        (
            {"user-agent": "Codex Desktop/0.159.2", "x-stainless-lang": "python"},
            502,
            "previous_response_owner_unavailable",
            "early",
        ),
        ({"user-agent": "Codex Desktop/0.159.2"}, 400, "continuity_recovery_required", "timeout"),
        ({"user-agent": "Codex Desktop/0.159.2"}, 400, "continuity_recovery_required", "late_pressure"),
        ({"user-agent": "Codex Desktop/0.159.2"}, 502, "previous_response_owner_unavailable", "no_alternate"),
        ({"user-agent": "Codex Desktop/0.159.2"}, 502, "previous_response_owner_unavailable", "recheck_timeout"),
        ({"user-agent": "Codex Desktop/0.159.2"}, 502, "previous_response_owner_unavailable", "recheck_failure"),
        ({"user-agent": "Codex Desktop/0.159.2"}, 502, "previous_response_owner_unavailable", "recheck_empty"),
        ({"user-agent": "Codex Desktop/0.159.2"}, 502, "previous_response_owner_unavailable", "recheck_wrong_owner"),
    ],
)
async def test_fresh_reattach_delta_route_requires_local_history_and_logs_preflight(
    async_client,
    app_instance,
    monkeypatch,
    caplog,
    identity_headers,
    expected_status,
    expected_code,
    admission_case,
):
    """Reproduce the PC2 HTTP-only failure at the public backend route.

    A fresh process has only durable owner continuity. The client sends a delta,
    so the proxy injects the stored anchor. The owner is quota-blocked and a
    healthy alternate exists, but the delta cannot move without losing context.
    The route must return one explicit recovery-required refusal and must not
    create an upstream session on either account.
    """

    _install_bridge_settings(monkeypatch, enabled=True)
    caplog.set_level(logging.INFO, logger="app.modules.proxy.service")
    service = get_proxy_service_for_app(app_instance)
    thread_id = "thread-local-history-recovery-required"
    durable_lookup = DurableBridgeLookup(
        session_id="durable-local-history-recovery",
        canonical_kind="session_header",
        canonical_key="sid-local-history-recovery",
        api_key_scope="__anonymous__",
        account_id="acc-owner",
        owner_instance_id="bridge-instance",
        owner_process_epoch=http_bridge_owner_process_epoch(),
        owner_epoch=7,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        state=HttpBridgeSessionState.ACTIVE,
        latest_turn_state="sid-local-history-recovery",
        latest_response_id="resp_owner_anchor",
        model="gpt-5.1",
    )
    get_or_create = AsyncMock(side_effect=AssertionError("local-history refusal must precede upstream creation"))
    retire_owner = AsyncMock(return_value=True)
    advice_calls = 0
    if admission_case != "early":
        get_or_create.side_effect = [
            ProxyResponseError(
                502,
                {
                    "error": {
                        "type": "server_error",
                        "code": "previous_response_owner_unavailable",
                        "message": "Owner unavailable",
                    }
                },
            ),
            AssertionError("an unproven delta must not be retried after clearing the owner"),
        ]

    async def quota_owner_advice(*args, **kwargs):
        del args, kwargs
        nonlocal advice_calls
        advice_calls += 1
        if admission_case in {"timeout", "recheck_timeout"} and (
            advice_calls == 1 or admission_case == "recheck_timeout"
        ):
            raise TimeoutError("synthetic read-only advisory timeout")
        if admission_case != "early" and advice_calls == 1:
            return None
        if admission_case == "recheck_failure":
            raise RuntimeError("synthetic advisory-store failure")
        if admission_case == "recheck_empty":
            return None
        return OwnerRecoveryAdvice(
            owner_id="acc-wrong-owner" if admission_case == "recheck_wrong_owner" else "acc-owner",
            hint=OwnerRecoveryHint("quota_exhausted", time.time() + 3600),
            alternate_id=None if admission_case == "no_alternate" else "acc-alternate",
        )

    monkeypatch.setattr(bridge_streaming, "assess_owner_recovery", quota_owner_advice)
    monkeypatch.setattr(service._durable_bridge, "lookup_request_targets", AsyncMock(return_value=durable_lookup))
    monkeypatch.setattr(service, "_http_bridge_has_live_local_session", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_http_bridge_can_forward_to_active_owner", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_resolve_file_account_for_responses", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_resolve_websocket_previous_response_owner", AsyncMock(return_value="acc-owner"))
    monkeypatch.setattr(service, "_get_or_create_http_bridge_session", get_or_create)
    monkeypatch.setattr(service._durable_bridge, "retire_continuity_owner_if_unavailable", retire_owner)

    response = await async_client.post(
        "/backend-api/codex/responses",
        json={
            "model": "gpt-5.1",
            "instructions": "continue",
            "stream": True,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "delta-only continuation"}],
                }
            ],
        },
        headers={
            "session_id": "sid-local-history-recovery",
            "thread-id": thread_id,
            **identity_headers,
        },
    )

    assert response.status_code == expected_status
    error = response.json()["error"]
    assert error["code"] == expected_code
    if expected_code == "continuity_recovery_required":
        assert error["type"] == "invalid_request_error"
        assert "local Codex session history" in error["message"]
        assert "param" not in error
        assert response.headers["x-should-retry"] == "false"
        assert "retry-after" not in response.headers
    else:
        assert response.headers.get("x-should-retry") != "false"
    retire_owner.assert_not_awaited()
    if admission_case == "early":
        get_or_create.assert_not_awaited()
    else:
        get_or_create.assert_awaited_once()
        assert get_or_create.await_args.kwargs["previous_response_id"] == "resp_owner_anchor"

    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(RequestLog).where(
                        RequestLog.error_code == expected_code,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].account_id is None
    assert rows[0].model == "gpt-5.1"
    assert rows[0].request_id == response.headers["x-request-id"]
    recovery_events = [
        record.getMessage()
        for record in caplog.records
        if "event=owner_pressure_local_history_recovery_required " in record.getMessage()
    ]
    assert len(recovery_events) == (1 if expected_code == "continuity_recovery_required" else 0)
    assert all("resp_owner_anchor" not in event and "delta-only continuation" not in event for event in recovery_events)
    if expected_code == "continuity_recovery_required" or identity_headers.get("user-agent", "").lower().startswith(
        "codex"
    ):
        assert rows[0].conversation_id == thread_id


@pytest.mark.asyncio
@pytest.mark.parametrize("local_provenance", [True, False])
async def test_recovery_preflight_logging_does_not_classify_provider_errors_by_code_alone(
    async_client,
    app_instance,
    monkeypatch,
    local_provenance,
):
    _install_bridge_settings(monkeypatch, enabled=True)
    service = get_proxy_service_for_app(app_instance)
    error = ProxyResponseError(
        400,
        _local_history_recovery_required_error(),
        failure_phase="pre_dispatch" if local_provenance else "upstream",
        failure_detail="local_history_recovery_required" if local_provenance else None,
        local_pre_dispatch_refusal=local_provenance,
    )

    async def failed_bridge(*args, **kwargs):
        raise error
        yield ""  # pragma: no cover -- preserve async-generator shape

    preflight = AsyncMock()
    monkeypatch.setattr(service, "_stream_via_http_bridge", failed_bridge)
    monkeypatch.setattr(service, "_write_stream_preflight_error", preflight)
    response = await async_client.post(
        "/backend-api/codex/responses",
        json={"model": "gpt-5.1", "instructions": "test", "input": "test-only", "stream": True},
        headers={"user-agent": "Codex Desktop/0.159.2"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "continuity_recovery_required"
    if local_provenance:
        preflight.assert_awaited_once()
        assert preflight.await_args is not None
        assert preflight.await_args.kwargs["account_id"] is None
        assert preflight.await_args.kwargs["error_code"] == "continuity_recovery_required"
        assert response.headers["x-should-retry"] == "false"
    else:
        preflight.assert_not_awaited()
        assert "x-should-retry" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("store_mode", ["delayed", "failed", "timeout", "cancel"])
async def test_local_recovery_log_acknowledgement_preserves_refusal_and_cleanup(
    async_client, app_instance, monkeypatch, caplog, store_mode
):
    _install_bridge_settings(monkeypatch, enabled=True)
    service = get_proxy_service_for_app(app_instance)
    started = asyncio.Event()
    # The shared fixture drains logs in a response hook, which hides the real
    # wire-order race. Observe the API itself and drain explicitly in finally.
    monkeypatch.setitem(async_client.event_hooks, "response", [])
    allow_write = asyncio.Event()
    committed = asyncio.Event()
    persist = service._persist_request_log
    reservation = ApiKeyUsageReservationData("reservation-local-refusal", "key-local-refusal", "gpt-5.1")
    release = AsyncMock()

    async def controlled_persist(**kwargs):
        started.set()
        await allow_write.wait()
        if store_mode == "failed":
            raise RuntimeError("synthetic preflight store failure")
        await persist(**kwargs)
        committed.set()

    async def failed_bridge(*args, **kwargs):
        raise ProxyResponseError(
            400,
            _local_history_recovery_required_error(),
            failure_phase="pre_dispatch",
            failure_detail="local_history_recovery_required",
            local_pre_dispatch_refusal=True,
        )
        yield ""  # pragma: no cover

    monkeypatch.setattr(service, "_persist_request_log", controlled_persist)
    monkeypatch.setattr(service, "_stream_via_http_bridge", failed_bridge)
    monkeypatch.setattr(proxy_api, "_enforce_request_limits", AsyncMock(return_value=reservation))
    monkeypatch.setattr(proxy_api, "_release_reservation", release)
    request_task = asyncio.create_task(
        async_client.post(
            "/backend-api/codex/responses",
            json={"model": "gpt-5.1", "instructions": "test", "input": "delta", "stream": True},
            headers={"originator": "codex_cli_rs", "thread-id": "thread-log-ack"},
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        if store_mode == "delayed":
            done, _ = await asyncio.wait({request_task}, timeout=0.03)
            assert not done, "the refusal escaped before its healthy preflight log was acknowledged"
            allow_write.set()
        elif store_mode == "failed":
            allow_write.set()
        elif store_mode == "cancel":
            request_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request_task
            assert service._request_log_tasks
            assert all(not task.cancelled() for task in service._request_log_tasks)
            release.assert_awaited_once_with(reservation)
            return
        response = await asyncio.wait_for(asyncio.shield(request_task), timeout=3)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "continuity_recovery_required"
        assert response.headers["x-should-retry"] == "false"
        release.assert_awaited_once_with(reservation)
        if store_mode == "delayed":
            assert committed.is_set()
        elif store_mode == "timeout":
            assert not committed.is_set()
            assert "Preflight request log acknowledgement timed out" in caplog.text
            assert service._request_log_tasks
        else:
            assert "Request log persistence task failed" in caplog.text
    finally:
        allow_write.set()
        if not request_task.done():
            request_task.cancel()
        await asyncio.gather(request_task, return_exceptions=True)
        assert await service.drain_persistence_tasks(timeout_seconds=3)
        if store_mode != "failed":
            async with SessionLocal() as session:
                rows = list(
                    (
                        await session.execute(select(RequestLog).where(RequestLog.conversation_id == "thread-log-ack"))
                    ).scalars()
                )
            assert len(rows) == 1


@pytest.mark.asyncio
async def test_committed_recovery_refusal_route_retains_terminal_wire_contract(async_client, app_instance, monkeypatch):
    _install_bridge_settings(monkeypatch, enabled=True)
    service = get_proxy_service_for_app(app_instance)
    reservation = ApiKeyUsageReservationData("reservation-committed", "key-committed", "gpt-5.1")
    release = AsyncMock()

    async def failed_bridge(*args, **kwargs):
        # The first event commits startup; the later refusal is still locally
        # proven pre-dispatch, not a terminated upstream transport.
        yield 'event: codex.rate_limits\ndata: {"type":"codex.rate_limits"}\n\n'
        raise ProxyResponseError(
            400,
            _local_history_recovery_required_error(),
            failure_phase="pre_dispatch",
            failure_detail="local_history_recovery_required",
            local_pre_dispatch_refusal=True,
            retry_after_seconds=60,
        )

    monkeypatch.setattr(service, "_stream_via_http_bridge", failed_bridge)
    monkeypatch.setattr(proxy_api, "_enforce_request_limits", AsyncMock(return_value=reservation))
    monkeypatch.setattr(proxy_api, "_release_reservation", release)
    response = await async_client.post(
        "/backend-api/codex/responses",
        json={"model": "gpt-5.1", "instructions": "test", "input": "delta", "stream": True},
        headers={"originator": "codex_cli_rs", "thread-id": "thread-committed-recovery"},
    )
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
    failures = [event for event in events if event.get("type") == "response.failed"]
    assert len(failures) == 1
    error = failures[0]["response"]["error"]
    assert error["code"] == "invalid_prompt"
    assert error["type"] == "invalid_request_error"
    assert error["availability_reason"] == "continuity_recovery_required"
    assert "local Codex session history" in error["message"]
    assert "retry:" not in response.text
    assert "previous_response_not_found" not in response.text
    release.assert_awaited_once_with(reservation)
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(RequestLog).where(RequestLog.conversation_id == "thread-committed-recovery")
                )
            ).scalars()
        )
    assert len(rows) == 1
    assert rows[0].account_id is None
    assert rows[0].error_code == "continuity_recovery_required"


@pytest_asyncio.fixture
async def pressured_continuation(async_client, app_instance, monkeypatch):
    """Use the real API/DB/selector with only the external upstream replaced."""
    _install_bridge_settings(monkeypatch, enabled=True)
    owner_id = await _import_account(async_client, "guard_owner", "guard-owner@example.com")
    owner = await _get_account(owner_id)
    original = _FakeBridgeUpstreamWebSocket("resp_guard_owner")
    replacement = _FakeBridgeUpstreamWebSocket("resp_guard_alternate")
    connections = []

    async def fresh(self, account, *, force=False, timeout_seconds):
        return account

    async def connect(headers, access_token, account_id_header, *, base_url=None, session=None):
        connections.append(account_id_header)
        return original if account_id_header == owner.chatgpt_account_id else replacement

    monkeypatch.setattr(proxy_module.ProxyService, "_ensure_fresh_with_budget", fresh)
    monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
    first_input = [{"role": "user", "content": [{"type": "input_text", "text": "retain this context"}]}]
    base = {"model": "gpt-5.1", "instructions": "Return OK.", "reasoning": {"effort": "high"}, "stream": True}
    headers = {"session_id": "owner-recovery-guard-test"}
    events = await _collect_sse_events(
        async_client, "/backend-api/codex/responses", json_body={**base, "input": first_input}, headers=headers
    )
    first = events[-1]["response"]
    alternate_id = await _import_account(async_client, "guard_alternate", "guard-alternate@example.com")
    now = int(time.time())
    async with SessionLocal() as session:
        await session.execute(
            update(Account)
            .where(Account.id == owner_id)
            .values(status=AccountStatus.RATE_LIMITED, blocked_at=now - 1, reset_at=now + 31)
        )
        for account_id in (owner_id, alternate_id):
            for window, minutes in (("primary", 300), ("secondary", 10080)):
                session.add(
                    UsageHistory(
                        account_id=account_id,
                        window=window,
                        used_percent=10,
                        reset_at=now + 7200,
                        window_minutes=minutes,
                        recorded_at=to_utc_naive(utcnow()),
                    )
                )
        await session.commit()
    get_account_selection_cache().invalidate()
    body = {
        **base,
        "input": [
            *first_input,
            first["output"][0],
            {"role": "user", "content": [{"type": "input_text", "text": "continue without dropping prior context"}]},
        ],
    }
    return SimpleNamespace(
        client=async_client,
        service=get_proxy_service_for_app(app_instance),
        owner_id=owner_id,
        alternate_id=alternate_id,
        original=original,
        replacement=replacement,
        body=body,
        headers=headers,
        first=first,
        connections=connections,
        now=now,
    )


@pytest.mark.asyncio
async def test_31_second_owner_hold_transfers_without_waiting_or_rejecting_upstream(
    pressured_continuation, monkeypatch
):
    case = pressured_continuation

    async def unexpected_wait(**kwargs):
        raise AssertionError("A 31-second hold must not park or submit early")
        yield  # pragma: no cover -- keep the streaming seam's async-generator shape

    monkeypatch.setattr(bridge_streaming, "_iter_account_capacity_wait_sse", unexpected_wait)
    events = await _collect_sse_events(
        case.client, "/backend-api/codex/responses", json_body=case.body, headers=case.headers
    )
    assert events[-1]["response"]["id"] == "resp_guard_alternate_1"
    assert len(case.original.sent_text) == 1
    sent = json.loads(case.replacement.sent_text[0])
    assert sent["input"] == case.body["input"]
    assert sent["model"] == case.body["model"]
    assert sent["reasoning"] == case.body["reasoning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("constraint", ["explicit_anchor", "missing_output", "file_owner", "no_alternate"])
async def test_blocked_unmovable_turn_never_dispatches_to_either_account(
    pressured_continuation, monkeypatch, constraint
):
    case = pressured_continuation
    if constraint == "explicit_anchor":
        case.body["previous_response_id"] = case.first["id"]
    elif constraint == "missing_output":
        case.body["input"] = [case.body["input"][0], case.body["input"][-1]]
    elif constraint == "file_owner":

        async def file_owner(*args, **kwargs):
            return case.owner_id

        monkeypatch.setattr(case.service, "_resolve_file_account_for_responses", file_owner)
    else:
        async with SessionLocal() as session:
            await session.execute(
                update(Account).where(Account.id == case.alternate_id).values(status=AccountStatus.PAUSED)
            )
            await session.commit()
        get_account_selection_cache().invalidate()
    response = await case.client.post("/backend-api/codex/responses", json=case.body, headers=case.headers)
    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "previous_response_owner_unavailable"
    assert error["resets_at"] == case.now + 31
    assert len(case.original.sent_text) == 1
    assert case.replacement.sent_text == []
    assert all(runtime.inflight_response_creates == 0 for runtime in case.service._load_balancer._runtime.values())


@pytest.mark.asyncio
async def test_alternate_is_revalidated_after_advisory_selection_race(pressured_continuation, monkeypatch):
    case = pressured_continuation
    assess = bridge_streaming.assess_owner_recovery

    async def stale_advice(*args, **kwargs):
        advice = await assess(*args, **kwargs)
        assert advice is not None and advice.alternate_id == case.alternate_id
        async with SessionLocal() as session:
            await session.execute(
                update(Account).where(Account.id == case.alternate_id).values(status=AccountStatus.PAUSED)
            )
            await session.commit()
        get_account_selection_cache().invalidate()
        return advice

    monkeypatch.setattr(bridge_streaming, "assess_owner_recovery", stale_advice)
    response = await case.client.post("/backend-api/codex/responses", json=case.body, headers=case.headers)
    assert response.status_code in (502, 503)
    assert len(case.original.sent_text) == 1
    assert case.replacement.sent_text == []
    assert all(runtime.inflight_response_creates == 0 for runtime in case.service._load_balancer._runtime.values())


@pytest.mark.asyncio
async def test_advisory_timeout_does_not_break_a_healthy_owner(pressured_continuation, monkeypatch):
    case = pressured_continuation
    async with SessionLocal() as session:
        await session.execute(
            update(Account)
            .where(Account.id == case.owner_id)
            .values(
                status=AccountStatus.ACTIVE,
                blocked_at=None,
                reset_at=None,
            )
        )
        await session.commit()
    get_account_selection_cache().invalidate()

    async def timed_out(*args, **kwargs):
        raise TimeoutError("Synthetic advisory timeout")

    monkeypatch.setattr(bridge_streaming, "assess_owner_recovery", timed_out)
    events = await _collect_sse_events(
        case.client, "/backend-api/codex/responses", json_body=case.body, headers=case.headers
    )
    assert events[-1]["response"]["id"] == "resp_guard_owner_2"
    assert case.replacement.sent_text == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,used", [(AccountStatus.ACTIVE, 96), (AccountStatus.RATE_LIMITED, 100)])
async def test_existing_socket_moves_complete_next_turn_before_owner_rejection(
    async_client,
    app_instance,
    monkeypatch,
    status,
    used,
):
    _install_bridge_settings(monkeypatch, enabled=True)
    owner_id = await _import_account(async_client, "pressure_owner", "pressure-owner@example.com")
    owner = await _get_account(owner_id)
    owner_socket = _FakeBridgeUpstreamWebSocket("resp_pressure_owner")
    replacement_socket = _FakeBridgeUpstreamWebSocket("resp_pressure_replacement")
    connected = []

    async def fresh(self, account, *, force=False, timeout_seconds):
        return account

    async def connect(headers, access_token, account_id_header, *, base_url=None, session=None):
        connected.append(account_id_header)
        return owner_socket if account_id_header == owner.chatgpt_account_id else replacement_socket

    monkeypatch.setattr(proxy_module.ProxyService, "_ensure_fresh_with_budget", fresh)
    monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
    first_input = [{"role": "user", "content": [{"type": "input_text", "text": "first turn"}]}]
    base = {"model": "gpt-5.1", "instructions": "Return exactly OK.", "reasoning": {"effort": "high"}, "stream": True}
    headers = {"session_id": "preemptive-owner-test"}
    events = await _collect_sse_events(
        async_client, "/backend-api/codex/responses", json_body={**base, "input": first_input}, headers=headers
    )
    first = events[-1]["response"]
    alternate_id = await _import_account(async_client, "pressure_alternate", "pressure-alternate@example.com")
    alternate = await _get_account(alternate_id)
    now = int(time.time())
    async with SessionLocal() as session:
        if status == AccountStatus.RATE_LIMITED:
            await session.execute(
                update(Account)
                .where(Account.id == owner_id)
                .values(
                    status=status,
                    blocked_at=now - 40,
                    reset_at=now - 9,
                )
            )
        for account_id, percent in [(owner_id, used), (alternate_id, 10)]:
            session.add(
                UsageHistory(
                    account_id=account_id,
                    window="primary",
                    used_percent=percent,
                    reset_at=now + 3600,
                    window_minutes=300,
                    recorded_at=to_utc_naive(utcnow()),
                )
            )
            session.add(
                UsageHistory(
                    account_id=account_id,
                    window="secondary",
                    used_percent=10,
                    reset_at=now + 7200,
                    window_minutes=10080,
                    recorded_at=to_utc_naive(utcnow()),
                )
            )
        await session.commit()
    get_account_selection_cache().invalidate()
    second_input = [
        *first_input,
        first["output"][0],
        {"role": "user", "content": [{"type": "input_text", "text": "second turn"}]},
    ]
    events = await _collect_sse_events(
        async_client, "/backend-api/codex/responses", json_body={**base, "input": second_input}, headers=headers
    )
    second = events[-1]["response"]
    assert second["id"] == "resp_pressure_replacement_1"
    assert len(owner_socket.sent_text) == 1  # no failing speculative send to owner
    assert connected == [owner.chatgpt_account_id, alternate.chatgpt_account_id]
    sent = json.loads(replacement_socket.sent_text[0])
    assert sent["input"] == second_input
    assert sent["reasoning"]["effort"] == "high"
    assert sent["model"] == base["model"]
    assert "previous_response_id" not in sent
    third_input = [
        *second_input,
        second["output"][0],
        {"role": "user", "content": [{"type": "input_text", "text": "third turn"}]},
    ]
    third_events = await _collect_sse_events(
        async_client,
        "/backend-api/codex/responses",
        json_body={**base, "input": third_input, "previous_response_id": second["id"]},
        headers=headers,
    )
    assert third_events[-1]["response"]["id"] == "resp_pressure_replacement_2"
    assert len(owner_socket.sent_text) == 1
    service = get_proxy_service_for_app(app_instance)
    assert all(runtime.inflight_response_creates == 0 for runtime in service._load_balancer._runtime.values())
