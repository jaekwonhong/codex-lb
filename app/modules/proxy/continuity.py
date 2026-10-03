"""Shared account-owner consistency checks for proxy continuity sources."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from hashlib import sha256
from typing import Protocol

from app.core.clients.proxy import ProxyResponseError, _is_native_codex_request
from app.core.errors import OpenAIErrorEnvelope, openai_error

HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KIND = "internal_unanchored_parallel"
HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KEY_PREFIX = "account-neutral-replay:v1:"
# These are canonical lanes whose exact aliases may move only after the
# existing full-resend validator has proved the request account-neutral. A
# thread lane is hard during ordinary use, just like a session-header lane;
# omitting it here would accidentally remove safe owner-unavailable recovery
# merely because Codex now supplies a more precise canonical identity.
HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_REBINDABLE_KINDS = frozenset(
    {"prompt_cache", "session_header", "thread_header", "turn_state_header"}
)
_HTTP_BRIDGE_SESSION_AFFINITY_HEADERS = frozenset(
    {
        "session_id",
        "session-id",
        "thread-id",
        "x-codex-conversation-id",
        "x-codex-session-id",
        "x-codex-turn-state",
    }
)
logger = logging.getLogger("app.modules.proxy.continuity")


def native_codex_recovery_contract(
    headers: Mapping[str, str],
    *,
    enforce_openai_sdk_contract: bool,
    codex_session_affinity: bool,
) -> bool:
    """Return whether native-only continuity recovery applies to this request.

    Some first-party Codex clients carry SDK implementation metadata, so the
    public response normalizer can conservatively select the SDK-compatible
    wire contract.  A native ``originator`` remains a stronger first-party
    identity signal for this narrow pre-dispatch recovery decision.  UA-only
    lookalikes do not gain this exemption.
    """

    if not codex_session_affinity or not _is_native_codex_request(headers):
        return False
    if not enforce_openai_sdk_contract:
        return True
    originator = next(
        (value for key, value in headers.items() if key.lower() == "originator"),
        None,
    )
    if bool(originator) and _is_native_codex_request({"originator": originator}):
        return True
    # First-party Desktop can omit originator while still carrying a stable
    # backend thread identity.  Do not use turn-state alone here: ordinary SDK
    # clients can replay that compatibility token.  A native Codex UA plus one
    # of these backend conversation/session identities is the narrow fallback.
    return any(
        key.lower() in {"thread-id", "x-codex-conversation-id", "x-codex-session-id"}
        and isinstance(value, str)
        and bool(value.strip())
        for key, value in headers.items()
    )


def local_history_recovery_required_error() -> OpenAIErrorEnvelope:
    """Describe a native continuation that cannot be replayed unchanged."""

    return openai_error(
        "continuity_recovery_required",
        (
            "This continuation cannot be safely reassigned with the context available to the proxy. "
            "Repeating it unchanged cannot restore context. Preserve this thread; wait for the original "
            "owner to become available or recover a new thread from local Codex session history."
        ),
        error_type="invalid_request_error",
    )


def local_history_recovery_refusal() -> ProxyResponseError:
    """Return the typed pre-dispatch refusal understood by the public wrapper."""

    return ProxyResponseError(
        400,
        local_history_recovery_required_error(),
        failure_phase="pre_dispatch",
        failure_detail="local_history_recovery_required",
        local_pre_dispatch_refusal=True,
    )


def is_local_history_recovery_required(error: ProxyResponseError) -> bool:
    """Recognize only proxy-authored recovery refusals, not provider lookalikes."""

    detail = error.payload.get("error")
    return (
        error.status_code == 400
        and error.local_pre_dispatch_refusal
        and error.failure_phase == "pre_dispatch"
        and error.failure_detail == "local_history_recovery_required"
        and isinstance(detail, dict)
        and detail.get("code") == "continuity_recovery_required"
        and detail.get("type") == "invalid_request_error"
    )


def make_http_bridge_account_neutral_replay_key(nonce: str) -> tuple[str, str]:
    if not nonce:
        raise ValueError("account-neutral replay nonce must not be empty")
    return (
        HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KIND,
        f"{HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KEY_PREFIX}{nonce}",
    )


def is_http_bridge_account_neutral_replay(*, kind: str, key: str) -> bool:
    """Recognize only server-namespaced durable replay keys."""

    return (
        kind == HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KIND
        and key.startswith(HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KEY_PREFIX)
        and len(key) > len(HTTP_BRIDGE_ACCOUNT_NEUTRAL_REPLAY_KEY_PREFIX)
    )


def without_http_bridge_session_affinity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Drop downstream aliases that must not reach a fresh upstream account."""

    return {
        header_name: header_value
        for header_name, header_value in headers.items()
        if header_name.lower() not in _HTTP_BRIDGE_SESSION_AFFINITY_HEADERS
    }


class _ReconnectPreferredOwner(Protocol):
    preferred_account_id: str | None
    file_required_preferred_account: bool


def resolve_reconnect_preferred_account_id(
    request_state: _ReconnectPreferredOwner,
    session_account_id: str,
    require_preferred_account: bool,
    account_neutral_recovery: bool,
) -> str | None:
    if request_state.file_required_preferred_account:
        return request_state.preferred_account_id or session_account_id
    if require_preferred_account or account_neutral_recovery:
        return request_state.preferred_account_id
    return None


def resolve_required_account_id(*owners: tuple[str, str | None]) -> str | None:
    """Return one proven owner or fail closed when hard sources disagree."""
    resolved = [(source, account_id) for source, account_id in owners if account_id is not None]
    if not resolved:
        return None
    owner_account_id = resolved[0][1]
    conflicting_sources = [source for source, account_id in resolved if account_id != owner_account_id]
    if conflicting_sources:
        # Hard sources identify account-scoped upstream state. Choosing either
        # side would silently abandon the other, so conflicts are never ordered
        # by caller precedence or softened into ordinary affinity fallback.
        sources = ", ".join(source for source, _account_id in resolved)
        owner_hashes = ", ".join(
            f"{source}={sha256(account_id.encode()).hexdigest()[:12]}" for source, account_id in resolved
        )
        logger.warning(
            "continuity_owner_conflict sources=%s conflicting_sources=%s owner_hashes=%s",
            sources,
            ", ".join(conflicting_sources),
            owner_hashes,
        )
        raise ProxyResponseError(
            502,
            openai_error(
                "continuity_owner_conflict",
                f"Account-owned continuity sources conflict ({sources}); retry the logical turn.",
                error_type="server_error",
            ),
        )
    return owner_account_id
