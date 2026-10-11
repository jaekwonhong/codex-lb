from __future__ import annotations

from typing import Any, cast

import pytest

from app.core.clients.native_egress import NativeEgressProtocolError, NativeEgressTransportError, NativeEgressWebSocket
from app.core.clients.proxy_websocket import NativeUpstreamWebSocket

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("transport", "transport"),
        ("protocol", "protocol"),
        ("consumer_backpressure", "consumer_backpressure"),
        ("helper_read", "helper_read"),
        ("liveness_timeout", "liveness_timeout"),
        ("untrusted-phase:private-value", None),
        ("", None),
    ],
)
async def test_native_receive_reports_only_allowlisted_phase(phase: str, expected: str | None) -> None:
    class BrokenConnection:
        async def receive(self) -> None:
            raise NativeEgressTransportError("untrusted-private-message", failure_phase=phase)

    websocket = NativeUpstreamWebSocket(cast(NativeEgressWebSocket, cast(Any, BrokenConnection())))
    message = await websocket.receive()

    assert message.kind == "error"
    assert message.native_failure_phase == expected
    assert message.error == "Upstream websocket receive failed"
    expected_error_code = {
        "helper_read": "proxy_network_unavailable",
        "liveness_timeout": "upstream_websocket_liveness_timeout",
    }.get(phase)
    assert message.error_code == expected_error_code
    assert "private" not in message.error
    assert "private" not in str(message.native_failure_phase)


@pytest.mark.asyncio
async def test_native_protocol_exception_has_no_raw_diagnostic_text() -> None:
    class BrokenConnection:
        async def receive(self) -> None:
            raise NativeEgressProtocolError("untrusted-private-message")

    websocket = NativeUpstreamWebSocket(cast(NativeEgressWebSocket, cast(Any, BrokenConnection())))
    message = await websocket.receive()

    assert message.native_failure_phase == "protocol"
    assert message.error == "Upstream websocket receive failed"
