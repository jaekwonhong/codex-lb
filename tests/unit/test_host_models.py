from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.openai.host_models import resolve_default_host_model

pytestmark = pytest.mark.unit


def test_default_host_model_prefers_visible_luna(monkeypatch):
    registry = SimpleNamespace(
        plan_types_for_model=lambda slug: {"pro"} if slug in {"gpt-5.6-luna", "gpt-5.5"} else set(),
        is_suppressed_model=lambda _slug: False,
    )
    monkeypatch.setattr("app.core.openai.host_models.get_model_registry", lambda: registry)

    assert resolve_default_host_model() == "gpt-5.6-luna"


def test_default_host_model_falls_back_to_visible_legacy_host(monkeypatch):
    registry = SimpleNamespace(
        plan_types_for_model=lambda slug: {"pro"} if slug == "gpt-5.5" else set(),
        is_suppressed_model=lambda slug: slug == "gpt-5.6-luna",
    )
    monkeypatch.setattr("app.core.openai.host_models.get_model_registry", lambda: registry)

    assert resolve_default_host_model() == "gpt-5.5"
