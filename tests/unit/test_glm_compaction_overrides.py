from __future__ import annotations

import json

from app.core.types import JsonValue
from app.modules.proxy.api import (
    _GLM_COMPACTION_OUTPUT_TOKENS,
    _apply_glm_compaction_request_overrides,
)


def _headers(request_kind: str) -> dict[str, str]:
    return {"x-codex-turn-metadata": json.dumps({"request_kind": request_kind})}


def test_glm_compaction_adds_bounded_output_budget_and_low_reasoning() -> None:
    payload: dict[str, JsonValue] = {
        "model": "glm5.3-flash",
        "reasoning": {"effort": "high", "summary": "auto"},
    }

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload["max_output_tokens"] == _GLM_COMPACTION_OUTPUT_TOKENS
    assert payload["reasoning"] == {"effort": "low", "summary": "auto"}


def test_glm_compaction_adds_reasoning_when_client_omits_it() -> None:
    payload: dict[str, JsonValue] = {"model": "glm5.3-flash"}

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload["max_output_tokens"] == _GLM_COMPACTION_OUTPUT_TOKENS
    assert payload["reasoning"] == {"effort": "low"}


def test_glm_compaction_respects_lower_source_output_ceiling() -> None:
    payload: dict[str, JsonValue] = {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(
        payload,
        _headers("compaction"),
        source_max_output_tokens=16_384,
    )

    assert payload["max_output_tokens"] == 16_384
    assert payload["reasoning"] == {"effort": "low"}


def test_glm_compaction_respects_lower_operator_request_override() -> None:
    payload: dict[str, JsonValue] = {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(
        payload,
        _headers("compaction"),
        source_max_output_tokens=65_536,
        source_override_max_output_tokens=8_192,
    )

    assert payload["max_output_tokens"] == 8_192
    assert payload["reasoning"] == {"effort": "low"}


def test_glm_compaction_preserves_api_key_reasoning_policy() -> None:
    payload: dict[str, JsonValue] = {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(
        payload,
        _headers("compaction"),
        source_max_output_tokens=32_768,
        preserve_reasoning_policy=True,
    )

    assert payload["max_output_tokens"] == 32_768
    assert payload["reasoning"] == {"effort": "high"}


def test_glm_normal_turn_is_unchanged() -> None:
    payload: dict[str, JsonValue] = {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(payload, _headers("normal"))

    assert payload == {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}


def test_other_model_compaction_is_unchanged() -> None:
    payload: dict[str, JsonValue] = {"model": "gpt-5.6-sol", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload == {"model": "gpt-5.6-sol", "reasoning": {"effort": "high"}}


def test_invalid_turn_metadata_does_not_enable_override() -> None:
    payload: dict[str, JsonValue] = {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(payload, {"x-codex-turn-metadata": "not-json"})

    assert payload == {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}
