from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import openai
import pytest
from starlette.requests import Request

from app.core.clients.proxy import ProxyResponseError
from app.core.utils.sse import parse_sse_data_json
from app.modules.proxy import api as proxy_api
from app.modules.proxy._service.http_bridge.helpers import (
    _is_local_history_recovery_required,
    _local_history_recovery_required_error,
)

pytestmark = pytest.mark.unit


def _local_refusal() -> ProxyResponseError:
    return ProxyResponseError(
        400,
        _local_history_recovery_required_error(),
        failure_phase="pre_dispatch",
        failure_detail="local_history_recovery_required",
        local_pre_dispatch_refusal=True,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/backend-api/codex/responses",
            "headers": [(b"user-agent", b"Codex Desktop/0.159.2")],
        }
    )


def test_local_refusal_has_actionable_non_stale_anchor_error() -> None:
    error = _local_refusal()
    assert _is_local_history_recovery_required(error)
    detail = error.payload["error"]
    assert detail["type"] == "invalid_request_error"
    assert detail["code"] == "continuity_recovery_required"
    assert "Preserve this thread" in detail["message"]
    assert "wait for the original owner" in detail["message"]
    assert "local Codex session history" in detail["message"]
    assert "param" not in detail
    assert "previous_response_id" not in detail["message"]


@pytest.mark.parametrize("missing_evidence", ["status", "local", "phase", "detail", "code", "type"])
def test_same_named_error_requires_all_local_provenance(missing_evidence: str) -> None:
    error = _local_refusal()
    if missing_evidence == "status":
        error.status_code = 409
    elif missing_evidence == "local":
        error.local_pre_dispatch_refusal = False
    elif missing_evidence == "phase":
        error.failure_phase = "upstream"
    elif missing_evidence == "detail":
        error.failure_detail = None
    elif missing_evidence == "code":
        error.payload["error"]["code"] = "previous_response_not_found"
    else:
        error.payload["error"]["type"] = "server_error"
    assert not _is_local_history_recovery_required(error)


def test_local_refusal_removes_conflicting_retry_hints_without_mutating_headers() -> None:
    error = _local_refusal()
    error.retry_after_seconds = 60
    error.retry_after_header = "60"
    headers = {
        "Retry-After": "60",
        "retry-after": "30",
        "Retry-After-Ms": "30000",
        "X-Should-Retry": "true",
        "x-request-id": "req-local-history-test",
    }
    original = headers.copy()
    response = proxy_api._stream_startup_error_response(_request(), error, headers=headers)
    assert response.status_code == 400
    assert response.headers["x-should-retry"] == "false"
    assert "retry-after" not in response.headers
    assert "retry-after-ms" not in response.headers
    assert response.headers["x-request-id"] == "req-local-history-test"
    assert headers == original


def test_unmarked_same_named_provider_error_preserves_its_retry_hints() -> None:
    error = ProxyResponseError(400, _local_history_recovery_required_error(), retry_after_seconds=7)
    response = proxy_api._stream_startup_error_response(_request(), error, headers={})
    assert response.headers["retry-after"] == "7"
    assert "x-should-retry" not in response.headers


def test_official_sdk_does_not_retry_actual_local_refusal_response() -> None:
    response = proxy_api._stream_startup_error_response(_request(), _local_refusal(), headers={})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(response.status_code, content=bytes(response.body), headers=dict(response.headers))

    with openai.OpenAI(
        api_key="test-only",
        base_url="https://example.invalid/backend-api/codex/",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(openai.BadRequestError):
            client.responses.create(model="gpt-5.1", input="test-only", stream=True)
    assert len(requests) == 1


def test_legacy_409_retries_in_official_sdk() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            409,
            json={"error": {"code": "continuity_recovery_required", "type": "server_error", "message": "test"}},
            headers={"retry-after-ms": "1"},
        )

    with openai.OpenAI(
        api_key="test-only",
        base_url="https://example.invalid/backend-api/codex/",
        max_retries=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(openai.ConflictError):
            client.responses.create(model="gpt-5.1", input="test-only", stream=True)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_committed_native_stream_delivers_local_refusal_not_transport_eof() -> None:
    refusal = _local_refusal()
    refusal.retry_after_seconds = 60

    async def source() -> AsyncIterator[str]:
        yield ": already committed\n\n"
        raise refusal

    raw_stream = proxy_api._stream_response_error_events(
        source(),
        owns_reservation=False,
        reservation=None,
        preserve_native_failure_lifecycle=True,
    )
    stream = proxy_api._normalize_public_responses_stream(
        raw_stream,
        enforce_openai_sdk_contract=False,
        preserve_native_failure_lifecycle=True,
    )
    chunks = [chunk async for chunk in stream]
    events = [event for chunk in chunks if (event := parse_sse_data_json(chunk)) is not None]
    assert len(events) == 1
    assert events[0]["type"] == "response.failed"
    response = events[0]["response"]
    assert isinstance(response, dict)
    error = response["error"]
    assert isinstance(error, dict)
    assert error["code"] == "invalid_prompt"
    assert error["type"] == "invalid_request_error"
    assert error["availability_reason"] == "continuity_recovery_required"
    assert "local Codex session history" in error["message"]
    assert "previous_response_not_found" not in json.dumps(events)
    assert not any(chunk.startswith("retry:") for chunk in chunks)
