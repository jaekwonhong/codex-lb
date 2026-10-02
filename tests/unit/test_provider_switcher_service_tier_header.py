from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from starlette.datastructures import Headers

from app.core.clients.proxy import CODEX_LB_SERVICE_TIER_HEADER, filter_inbound_headers
from app.core.openai.exceptions import ClientPayloadError
from app.core.openai.requests import ResponsesRequest
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy.api import (
    _apply_provider_switcher_service_tier_header,
    _clear_provider_switcher_service_tier_for_model_source,
)


def _payload(service_tier: str | None = None) -> ResponsesRequest:
    body: dict[str, object] = {
        "model": "gpt-6-astra",
        "instructions": "",
        "input": [],
    }
    if service_tier is not None:
        body["service_tier"] = service_tier
    return ResponsesRequest.model_validate(body)


def _api_key(*, enforced_service_tier: str | None = None) -> ApiKeyData:
    return cast(
        ApiKeyData,
        SimpleNamespace(id="provider-switcher-test", enforced_service_tier=enforced_service_tier),
    )


@pytest.mark.parametrize("header_value", ["priority", "fast", "PRIORITY"])
def test_provider_switcher_fast_header_materializes_priority(header_value: str) -> None:
    payload = _payload()

    result = _apply_provider_switcher_service_tier_header(
        payload,
        Headers({CODEX_LB_SERVICE_TIER_HEADER: header_value}),
        api_key=_api_key(),
    )

    assert result == "priority"
    assert payload.service_tier == "priority"


def test_provider_switcher_standard_header_clears_stale_client_tier() -> None:
    payload = _payload("priority")

    result = _apply_provider_switcher_service_tier_header(
        payload,
        Headers({CODEX_LB_SERVICE_TIER_HEADER: "default"}),
        api_key=_api_key(),
    )

    assert result == "default"
    assert payload.service_tier is None


def test_provider_switcher_header_requires_api_key_authentication() -> None:
    with pytest.raises(ClientPayloadError, match="requires authenticated"):
        _apply_provider_switcher_service_tier_header(
            _payload(),
            Headers({CODEX_LB_SERVICE_TIER_HEADER: "priority"}),
            api_key=None,
        )


def test_provider_switcher_header_rejects_unsupported_value() -> None:
    with pytest.raises(ClientPayloadError, match="Unsupported"):
        _apply_provider_switcher_service_tier_header(
            _payload(),
            Headers({CODEX_LB_SERVICE_TIER_HEADER: "flex"}),
            api_key=_api_key(),
        )


def test_provider_switcher_header_rejects_conflicting_duplicates() -> None:
    headers = Headers(
        raw=[
            (CODEX_LB_SERVICE_TIER_HEADER.encode(), b"priority"),
            (CODEX_LB_SERVICE_TIER_HEADER.encode(), b"default"),
        ]
    )

    with pytest.raises(ClientPayloadError, match="Conflicting"):
        _apply_provider_switcher_service_tier_header(_payload(), headers, api_key=_api_key())


def test_provider_switcher_header_is_not_forwarded_upstream() -> None:
    filtered = filter_inbound_headers(
        {
            CODEX_LB_SERVICE_TIER_HEADER: "priority",
            "user-agent": "Codex Desktop/test",
        }
    )

    assert CODEX_LB_SERVICE_TIER_HEADER not in {key.lower(): value for key, value in filtered.items()}
    assert filtered["user-agent"] == "Codex Desktop/test"


def test_provider_switcher_speed_is_cleared_for_model_source() -> None:
    payload = _payload("priority")

    _clear_provider_switcher_service_tier_for_model_source(payload, "priority", api_key=_api_key())

    assert payload.service_tier is None


def test_api_key_enforced_tier_survives_model_source_clear() -> None:
    payload = _payload("priority")

    _clear_provider_switcher_service_tier_for_model_source(
        payload,
        "priority",
        api_key=_api_key(enforced_service_tier="priority"),
    )

    assert payload.service_tier == "priority"
