from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_beta_patch_packet import CONTRACT, VerificationError, verify


def _write_tree(
    root: Path,
    *,
    repository: str,
    selection: str,
    proxy_api: str,
    websocket_mixin: str | None = None,
    forwarding: str | None = None,
) -> None:
    files = {
        "app/modules/model_sources/repository.py": repository,
        "app/modules/model_sources/selection.py": selection,
        "app/modules/proxy/api.py": proxy_api,
        "app/modules/proxy/_service/websocket/mixin.py": websocket_mixin or _good_websocket_mixin(),
        "app/modules/model_sources/forwarding.py": forwarding or _good_forwarding(),
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _good_repository() -> str:
    return """
class ModelSourcesRepository:
    async def assigned_source_has_model(self, model, *, allowed_source_ids):
        return True
"""


def _good_selection() -> str:
    return """
async def source_scoped_model_requires_source(model, api_key, *, raw_model=None):
    assigned_source_ids = allowed_source_ids_for_api_key(api_key)
    if assigned_source_ids is None:
        return False
    if not assigned_source_ids:
        return True
    repository = ModelSourcesRepository(None)
    if await repository.assigned_source_has_model(model, allowed_source_ids=assigned_source_ids):
        return True
    return False

async def responses_model_is_source_owned(model, api_key, *, raw_model=None):
    return await source_scoped_model_requires_source(model, api_key, raw_model=raw_model)
"""


def _good_proxy_api() -> str:
    guard = """
    if (
        not source_route_excluded
        and not continuity_suppressed
        and await source_scoped_model_requires_source(model, api_key, raw_model=raw_model)
    ):
        return 503
"""
    return f"async def responses():\n{guard}\nasync def v1_responses():\n{guard}"


def _good_websocket_mixin() -> str:
    return """
async def proxy_responses_websocket():
    if await responses_model_is_source_owned(model, api_key, raw_model=raw_model):
        return False

async def _connect_proxy_websocket():
    if await responses_model_is_source_owned(model, api_key, raw_model=raw_model):
        return False
"""


def _good_forwarding() -> str:
    return """
def _edge_responses_payload(payload):
    if payload.get("model") != "glm5.3-flash":
        return payload
    include = payload.get("include")
    if isinstance(include, list):
        payload = {
            **payload,
            "include": [entry for entry in include if entry != "reasoning.encrypted_content"],
        }
    return {key: value for key, value in payload.items() if key != "encrypted_content"}

async def forward_responses(source, payload):
    payload = _edge_responses_payload(payload)
    return payload

async def stream_responses(source, payload):
    payload = _edge_responses_payload(payload)
    return payload
"""


def test_verify_accepts_ownership_aware_packet_contract(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=_good_selection(),
        proxy_api=_good_proxy_api(),
    )

    result = verify(tmp_path)

    assert result.contract == CONTRACT
    assert result.responses_guard_call_count == 2
    assert result.websocket_source_guard_call_count == 2
    assert result.dgx_responses_payload_call_count == 2


def test_verify_rejects_historical_registry_only_sync_helper(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection="""
def source_scoped_model_requires_source(model, api_key, *, raw_model=None):
    registry_models = get_model_registry().get_models_with_fallback()
    return model not in registry_models
""",
        proxy_api=_good_proxy_api(),
    )

    with pytest.raises(VerificationError, match="must be async"):
        verify(tmp_path)


def test_verify_rejects_guard_without_structural_or_continuity_bypass(tmp_path: Path) -> None:
    bad_guard = """
async def responses():
    if await source_scoped_model_requires_source(model, api_key, raw_model=raw_model):
        return 503

async def v1_responses():
    if await source_scoped_model_requires_source(model, api_key, raw_model=raw_model):
        return 503
"""
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=_good_selection(),
        proxy_api=bad_guard,
    )

    with pytest.raises(VerificationError, match="structural source-route exclusions"):
        verify(tmp_path)


def test_verify_rejects_missing_positive_ownership_query(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection="""
async def source_scoped_model_requires_source(model, api_key, *, raw_model=None):
    assigned_source_ids = allowed_source_ids_for_api_key(api_key)
    if not assigned_source_ids:
        return True
    return True
""",
        proxy_api=_good_proxy_api(),
    )

    with pytest.raises(VerificationError, match="positively query assigned-source model ownership"):
        verify(tmp_path)


def test_verify_rejects_missing_websocket_source_owned_guards(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=_good_selection(),
        proxy_api=_good_proxy_api(),
        websocket_mixin="""
async def proxy_responses_websocket():
    return True
""",
    )

    with pytest.raises(VerificationError, match="WebSocket source-owned provider boundary"):
        verify(tmp_path)


def test_verify_rejects_websocket_helper_without_dangling_scope_boundary(tmp_path: Path) -> None:
    selection = _good_selection().replace(
        "return await source_scoped_model_requires_source(model, api_key, raw_model=raw_model)",
        "return False",
    )
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=selection,
        proxy_api=_good_proxy_api(),
    )

    with pytest.raises(VerificationError, match="dangling source-scope fail-closed boundary"):
        verify(tmp_path)


def test_verify_rejects_unawaited_websocket_source_owned_guard(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=_good_selection(),
        proxy_api=_good_proxy_api(),
        websocket_mixin="""
async def proxy_responses_websocket():
    if responses_model_is_source_owned(model, api_key):
        return False

async def _connect_proxy_websocket():
    if await responses_model_is_source_owned(model, api_key):
        return False
""",
    )

    with pytest.raises(VerificationError, match="must await source resolution"):
        verify(tmp_path)


def test_verify_rejects_missing_edge_responses_payload_scrub(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=_good_selection(),
        proxy_api=_good_proxy_api(),
        forwarding="""
async def forward_responses(source, payload):
    return payload

async def stream_responses(source, payload):
    return payload
""",
    )

    with pytest.raises(VerificationError, match="encrypted-reasoning scrub helper is missing"):
        verify(tmp_path)


def test_verify_rejects_edge_payload_scrub_bound_to_source_id(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        repository=_good_repository(),
        selection=_good_selection(),
        proxy_api=_good_proxy_api(),
        forwarding="""
def _edge_responses_payload(source, payload):
    if source.id != "src_old_edge_source" or payload.get("model") != "glm5.3-flash":
        return payload
    include = payload.get("include")
    if isinstance(include, list):
        payload = {
            **payload,
            "include": [entry for entry in include if entry != "reasoning.encrypted_content"],
        }
    return {key: value for key, value in payload.items() if key != "encrypted_content"}

async def forward_responses(source, payload):
    payload = _edge_responses_payload(source, payload)
    return payload

async def stream_responses(source, payload):
    payload = _edge_responses_payload(source, payload)
    return payload
""",
    )

    with pytest.raises(VerificationError, match=r"must not depend on deployment-specific source\.id"):
        verify(tmp_path)
