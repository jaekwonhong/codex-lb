from __future__ import annotations

import json

from app.modules.proxy.api import (
    _GLM_COMPACTION_OUTPUT_TOKENS,
    _apply_glm_compaction_request_overrides,
)


def _headers(request_kind: str) -> dict[str, str]:
    return {"x-codex-turn-metadata": json.dumps({"request_kind": request_kind})}


def test_glm_compaction_adds_output_floor_and_low_reasoning() -> None:
    payload = {"model": "glm5.3-flash", "reasoning": {"effort": "high", "summary": "auto"}}

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload["max_output_tokens"] == _GLM_COMPACTION_OUTPUT_TOKENS
    assert payload["reasoning"] == {"effort": "low", "summary": "auto"}


def test_glm_compaction_raises_too_small_client_budget_to_floor() -> None:
    payload = {"model": "glm5.3-flash", "max_output_tokens": 8_000}

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload["max_output_tokens"] == _GLM_COMPACTION_OUTPUT_TOKENS
    assert payload["reasoning"] == {"effort": "low"}


def test_glm_compaction_pins_client_budget_to_serving_ceiling() -> None:
    payload = {"model": "glm5.3-flash", "max_output_tokens": 64_000, "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload["max_output_tokens"] == _GLM_COMPACTION_OUTPUT_TOKENS
    assert payload["reasoning"] == {"effort": "low"}


def test_glm_normal_turn_is_unchanged() -> None:
    payload = {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(payload, _headers("normal"))

    assert payload == {"model": "glm5.3-flash", "reasoning": {"effort": "high"}}


def test_other_model_compaction_is_unchanged() -> None:
    payload = {"model": "gpt-5.6-sol", "reasoning": {"effort": "high"}}

    _apply_glm_compaction_request_overrides(payload, _headers("compaction"))

    assert payload == {"model": "gpt-5.6-sol", "reasoning": {"effort": "high"}}
