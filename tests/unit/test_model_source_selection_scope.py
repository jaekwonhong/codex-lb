from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.modules.model_sources import selection as source_selection


class _Registry:
    def __init__(self, models: set[str]) -> None:
        self._models = models

    def get_models_with_fallback(self) -> dict[str, object]:
        return {model: object() for model in self._models}


def _key(*, assigned: list[str], allowed_models: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        source_assignment_scope_enabled=True,
        assigned_source_ids=assigned,
        allowed_models=allowed_models,
    )


def _install_source_ownership(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owned: dict[str, set[str]],
) -> list[tuple[str, set[str]]]:
    seen: list[tuple[str, set[str]]] = []

    class _Repository:
        def __init__(self, _session: object) -> None:
            pass

        async def assigned_source_has_model(self, model: str, *, allowed_source_ids: set[str]) -> bool:
            seen.append((model, set(allowed_source_ids)))
            return any(model in owned.get(source_id, set()) for source_id in allowed_source_ids)

    @asynccontextmanager
    async def _session():
        yield object()

    monkeypatch.setattr(source_selection, "ModelSourcesRepository", _Repository)
    monkeypatch.setattr(source_selection, "get_background_session", _session)
    return seen


@pytest.mark.asyncio
async def test_registry_miss_does_not_make_unrelated_assigned_source_own_subscription_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_selection, "get_model_registry", lambda: _Registry(set()))
    seen = _install_source_ownership(
        monkeypatch,
        owned={"src_dgx": {"glm5.3-flash"}},
    )

    requires_source = await source_selection.source_scoped_model_requires_source(
        "gpt-6-astra",
        _key(assigned=["src_dgx"]),
    )

    assert requires_source is False
    assert seen == [("gpt-6-astra", {"src_dgx"})]


@pytest.mark.asyncio
async def test_assigned_source_declaring_registry_miss_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_selection, "get_model_registry", lambda: _Registry(set()))
    _install_source_ownership(
        monkeypatch,
        owned={"src_dgx": {"glm5.3-flash"}},
    )

    requires_source = await source_selection.source_scoped_model_requires_source(
        "glm5.3-flash",
        _key(assigned=["src_dgx"]),
    )

    assert requires_source is True


@pytest.mark.asyncio
async def test_dangling_source_scope_keeps_registry_miss_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_selection, "get_model_registry", lambda: _Registry(set()))

    requires_source = await source_selection.source_scoped_model_requires_source(
        "source-only-model",
        _key(assigned=[]),
    )

    assert requires_source is True


@pytest.mark.asyncio
async def test_subscription_registry_membership_still_wins_before_source_ownership_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_selection, "get_model_registry", lambda: _Registry({"gpt-6-astra"}))
    seen = _install_source_ownership(
        monkeypatch,
        owned={"src_dgx": {"gpt-6-astra"}},
    )

    requires_source = await source_selection.source_scoped_model_requires_source(
        "gpt-6-astra",
        _key(assigned=["src_dgx"]),
    )

    assert requires_source is False
    assert seen == []


@pytest.mark.asyncio
async def test_exact_api_key_allowlist_filters_raw_candidate_before_source_ownership_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_selection, "get_model_registry", lambda: _Registry(set()))
    seen = _install_source_ownership(
        monkeypatch,
        owned={"src_alias": {"gpt-6-astra-preview"}},
    )

    requires_source = await source_selection.source_scoped_model_requires_source(
        "gpt-6-astra",
        _key(assigned=["src_alias"], allowed_models=["gpt-6-astra"]),
        raw_model="gpt-6-astra-preview",
    )

    assert requires_source is False
    assert seen == [("gpt-6-astra", {"src_alias"})]
