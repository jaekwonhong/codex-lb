from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.clients.rate_limit_reset_credits import (
    ConsumeResetCreditError,
    ConsumeResetCreditResponse,
    ResetCreditFetchError,
    ResetCreditItem,
    ResetCreditsResponse,
)
from app.core.crypto import TokenEncryptor
from app.db.models import Account, AccountStatus
from app.modules.rate_limit_reset_credits import api as reset_credits_api
from app.modules.rate_limit_reset_credits import rotation_resolution
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditRedeemEvidence,
    RotationResetCreditResolutionStatus,
    WeeklyRecoveryState,
    resolve_rotation_reset_credit,
)
from app.modules.rate_limit_reset_credits.store import RateLimitResetCreditsStore

pytestmark = pytest.mark.unit


class StubEncryptor(TokenEncryptor):
    def __init__(self) -> None:
        pass

    def decrypt(self, encrypted: bytes) -> str:
        return "decrypted-access-token"


class StubPostgresLockSession:
    def get_bind(self) -> Any:
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def execute(self, statement: Any, params: dict[str, str] | None = None) -> None:
        return None


async def _noop_refresh(account: Account) -> None:
    return None


async def _no_sleep(seconds: float) -> None:
    return None


def _account() -> Account:
    return Account(
        id="acc_rotation",
        chatgpt_account_id="workspace-rotation",
        email="rotation@example.com",
        plan_type="business",
        access_token_encrypted=b"encrypted",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=b"id",
        last_refresh=datetime(2026, 9, 13),
        status=AccountStatus.ACTIVE,
    )


def _credit(
    credit_id: str,
    *,
    status: str = "available",
    expires_at: str = "2026-09-20T00:00:00Z",
) -> ResetCreditItem:
    return ResetCreditItem.model_validate({"id": credit_id, "status": status, "expires_at": expires_at})


def _credits_response(
    credits: list[ResetCreditItem],
    *,
    available_count: int | None = None,
) -> ResetCreditsResponse:
    return ResetCreditsResponse(
        credits=credits,
        available_count=(
            available_count if available_count is not None else sum(credit.status == "available" for credit in credits)
        ),
    )


def _consume_response(
    credit_id: str,
    *,
    code: str = "reset",
    windows_reset: int = 1,
) -> ConsumeResetCreditResponse:
    return ConsumeResetCreditResponse.model_validate(
        {
            "code": code,
            "credit": {
                "id": credit_id,
                "status": "redeemed",
                "redeemed_at": "2026-09-13T00:00:00Z",
            },
            "windows_reset": windows_reset,
        }
    )


def _observer(states: list[WeeklyRecoveryState]):
    remaining = list(states)

    async def observe() -> WeeklyRecoveryState:
        if not remaining:
            raise AssertionError("observer called beyond the bounded sequence")
        return remaining.pop(0)

    return observe


@pytest.fixture(autouse=True)
def fake_redeem_ledger(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    ledger: dict[tuple[str, str], str] = {}

    async def get_pinned(account_id: str, redeem_request_id: str) -> str | None:
        return ledger.get((account_id, redeem_request_id))

    async def pin(account_id: str, redeem_request_id: str, credit_id: str) -> str:
        return ledger.setdefault((account_id, redeem_request_id), credit_id)

    monkeypatch.setattr(reset_credits_api, "get_pinned_redeem_credit_id", get_pinned)
    monkeypatch.setattr(reset_credits_api, "pin_redeem_request", pin)
    monkeypatch.setattr(rotation_resolution, "get_pinned_redeem_credit_id", get_pinned)
    return ledger


@pytest.fixture(autouse=True)
def fake_coordination_session(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def session():
        yield StubPostgresLockSession()

    async def resolve_direct(account: Account) -> None:
        return None

    monkeypatch.setattr(rotation_resolution, "get_background_session", session)
    monkeypatch.setattr(rotation_resolution, "_default_resolve_route", resolve_direct)


@pytest.mark.asyncio
async def test_rotation_usage_refresh_treats_successful_no_write_as_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalidations: list[None] = []

    class _UsageRefresher:
        async def force_refresh_result(self, account: Account) -> Any:
            assert account.id == "acc_rotation"
            return SimpleNamespace(fetch_succeeded=True, usage_written=False)

    class _SelectionCache:
        def invalidate(self) -> None:
            invalidations.append(None)

    monkeypatch.setattr(rotation_resolution, "get_account_selection_cache", lambda: _SelectionCache())
    refresh = rotation_resolution.build_rotation_usage_refresh_callback(_UsageRefresher())

    await refresh(_account())

    assert invalidations == [None]


@pytest.mark.asyncio
async def test_rotation_usage_refresh_rejects_failed_fetch() -> None:
    class _UsageRefresher:
        async def force_refresh_result(self, account: Account) -> Any:
            return SimpleNamespace(fetch_succeeded=False, usage_written=False)

    refresh = rotation_resolution.build_rotation_usage_refresh_callback(_UsageRefresher())

    with pytest.raises(RuntimeError, match="did not complete"):
        await refresh(_account())


@pytest.mark.asyncio
async def test_summary_zero_with_unknown_authority_is_unavailable_not_no_credit() -> None:
    # Rotation deliberately receives no account-summary count. A summary-side
    # displayed zero therefore cannot suppress this authoritative detail read.
    store = RateLimitResetCreditsStore()

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        raise ResetCreditFetchError(503, "detail unavailable", code="detail_unavailable")

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED]),
        refresh_usage=_noop_refresh,
        store=store,
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
    )

    assert store.get("acc_rotation") is None
    assert result.status is RotationResetCreditResolutionStatus.UNAVAILABLE
    assert result.error_code == "detail_unavailable"
    assert result.redeem_admitted is False


@pytest.mark.asyncio
async def test_authority_error_and_unreadable_pin_state_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        raise ResetCreditFetchError(503, "detail unavailable", code="detail_unavailable")

    async def pin_read_fails(account_id: str, redeem_request_id: str) -> str | None:
        raise RuntimeError("shared database unavailable")

    monkeypatch.setattr(rotation_resolution, "get_pinned_redeem_credit_id", pin_read_fails)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED]),
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
    )

    assert result.status is RotationResetCreditResolutionStatus.UNAVAILABLE
    assert result.error_code == "detail_unavailable"
    assert result.redeem_admitted is False


@pytest.mark.asyncio
async def test_absent_detail_snapshot_performs_fresh_authoritative_discovery() -> None:
    store = RateLimitResetCreditsStore()
    consume_calls: list[str] = []
    refresh_calls: list[str] = []

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([_credit("credit-1")])

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        consume_calls.append(credit_id)
        return _consume_response(credit_id)

    async def refresh_usage(account: Account) -> None:
        refresh_calls.append(account.id)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.RECOVERED]),
        refresh_usage=refresh_usage,
        store=store,
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
    )

    assert consume_calls == ["credit-1"]
    assert refresh_calls == ["acc_rotation"]
    assert result.status is RotationResetCreditResolutionStatus.USAGE_RECOVERED
    assert result.account_id == "acc_rotation"
    assert result.workspace_account_id == "workspace-rotation"
    assert result.redeem_admitted is True
    assert result.redeem_evidence is RotationResetCreditRedeemEvidence.RESPONSE_RECEIVED
    assert result.selected_credit_id == "credit-1"
    assert result.response_code == "reset"
    assert result.windows_reset == 1


@pytest.mark.asyncio
async def test_coordination_session_closes_before_weekly_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def coordination_session():
        events.append("session-open")
        try:
            yield StubPostgresLockSession()
        finally:
            events.append("session-closed")

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([_credit("credit-1")])

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        return _consume_response(credit_id)

    async def observe() -> WeeklyRecoveryState:
        events.append("weekly-observe")
        return WeeklyRecoveryState.RECOVERED

    monkeypatch.setattr(rotation_resolution, "get_background_session", coordination_session)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=observe,
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
    )

    assert result.status is RotationResetCreditResolutionStatus.USAGE_RECOVERED
    assert events == ["session-open", "session-closed", "weekly-observe"]


@pytest.mark.asyncio
async def test_fresh_authoritative_zero_confirms_no_redeemable_credit() -> None:
    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([], available_count=0)

    async def consume_fn(*args: Any, **kwargs: Any) -> ConsumeResetCreditResponse:
        raise AssertionError("zero-credit resolution must not consume")

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED]),
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
    )

    assert result.status is RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT
    assert result.account_id == "acc_rotation"
    assert result.workspace_account_id == "workspace-rotation"
    assert result.redeem_admitted is False
    assert result.redeem_evidence is RotationResetCreditRedeemEvidence.NOT_ADMITTED
    assert result.observations == ()


@pytest.mark.asyncio
async def test_code_reset_and_windows_reset_are_evidence_separate_from_recovery() -> None:
    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([_credit("credit-1")])

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        return _consume_response(credit_id, code="reset", windows_reset=0)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED] * 3),
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=_no_sleep,
    )

    assert result.response_code == "reset"
    assert result.windows_reset == 0
    assert result.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING


@pytest.mark.asyncio
async def test_already_redeemed_still_requires_weekly_reconciliation() -> None:
    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([_credit("credit-1")])

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        return _consume_response(credit_id, code="already_redeemed", windows_reset=0)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.RECOVERED]),
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
    )

    assert result.response_code == "already_redeemed"
    assert result.status is RotationResetCreditResolutionStatus.USAGE_RECOVERED
    assert result.redeem_admitted is True
    assert result.redeem_evidence is RotationResetCreditRedeemEvidence.RESPONSE_RECEIVED


@pytest.mark.asyncio
async def test_first_follow_up_exhausted_does_not_end_reconciliation_before_recovery() -> None:
    sleep_calls: list[float] = []

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([_credit("credit-1")])

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        return _consume_response(credit_id)

    async def sleep_fn(seconds: float) -> None:
        sleep_calls.append(seconds)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED, WeeklyRecoveryState.RECOVERED]),
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=sleep_fn,
    )

    assert list(result.observations) == [
        WeeklyRecoveryState.EXHAUSTED,
        WeeklyRecoveryState.RECOVERED,
    ]
    assert sleep_calls == [rotation_resolution.DEFAULT_RECONCILIATION_DELAY_SECONDS]
    assert result.status is RotationResetCreditResolutionStatus.USAGE_RECOVERED


@pytest.mark.asyncio
async def test_bounded_reconciliation_unresolved_ends_pending() -> None:
    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        return _credits_response([_credit("credit-1")])

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        return _consume_response(credit_id)

    result = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="rotation-R",
        observe_fresh_weekly=_observer(
            [WeeklyRecoveryState.EXHAUSTED, WeeklyRecoveryState.UNKNOWN, WeeklyRecoveryState.EXHAUSTED]
        ),
        refresh_usage=_noop_refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=_no_sleep,
    )

    assert result.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    assert len(result.observations) == 3
    assert result.redeem_admitted is True


@pytest.mark.asyncio
async def test_same_request_replay_never_consumes_second_credit(
    fake_redeem_ledger: dict[tuple[str, str], str],
) -> None:
    consume_calls: list[str] = []
    fetch_calls = 0

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        nonlocal fetch_calls
        fetch_calls += 1
        return _credits_response(
            [
                _credit("credit-1", expires_at="2026-09-14T00:00:00Z"),
                _credit("credit-2", expires_at="2026-09-15T00:00:00Z"),
            ]
        )

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        consume_calls.append(credit_id)
        return _consume_response(credit_id)

    store = RateLimitResetCreditsStore()
    first = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="stable-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED] * 3),
        refresh_usage=_noop_refresh,
        store=store,
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=_no_sleep,
    )
    second = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="stable-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED] * 3),
        refresh_usage=_noop_refresh,
        store=store,
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=_no_sleep,
    )

    assert first.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    assert second.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    assert consume_calls == ["credit-1"]
    assert fetch_calls == 1
    assert fake_redeem_ledger == {("acc_rotation", "stable-R"): "credit-1"}
    assert second.redeem_admitted is True
    assert first.redeem_evidence is RotationResetCreditRedeemEvidence.RESPONSE_RECEIVED
    assert second.redeem_evidence is RotationResetCreditRedeemEvidence.DURABLY_PINNED
    assert second.selected_credit_id == "credit-1"
    assert second.response_code is None


@pytest.mark.asyncio
async def test_ambiguous_consume_after_pin_never_replays_or_consumes_second_credit(
    fake_redeem_ledger: dict[tuple[str, str], str],
) -> None:
    consume_calls: list[str] = []
    fetch_calls = 0

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        nonlocal fetch_calls
        fetch_calls += 1
        return _credits_response(
            [
                _credit("credit-1", expires_at="2026-09-14T00:00:00Z"),
                _credit("credit-2", expires_at="2026-09-15T00:00:00Z"),
            ]
        )

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        consume_calls.append(credit_id)
        raise ConsumeResetCreditError(503, "consume outcome unknown", code="upstream_unavailable")

    store = RateLimitResetCreditsStore()
    first = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="ambiguous-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED] * 3),
        refresh_usage=_noop_refresh,
        store=store,
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=_no_sleep,
    )
    second = await resolve_rotation_reset_credit(
        _account(),
        redeem_request_id="ambiguous-R",
        observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED] * 3),
        refresh_usage=_noop_refresh,
        store=store,
        encryptor=StubEncryptor(),
        fetch_fn=fetch_fn,
        consume_fn=consume_fn,
        sleep_fn=_no_sleep,
    )

    assert first.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    assert second.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    assert first.redeem_evidence is RotationResetCreditRedeemEvidence.DURABLY_PINNED
    assert second.redeem_evidence is RotationResetCreditRedeemEvidence.DURABLY_PINNED
    assert first.selected_credit_id == "credit-1"
    assert second.selected_credit_id == "credit-1"
    assert consume_calls == ["credit-1"]
    assert fetch_calls == 1
    assert fake_redeem_ledger == {("acc_rotation", "ambiguous-R"): "credit-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("competitor_kind", ["manual", "automatic"])
async def test_manual_and_automatic_shapes_serialize_with_rotation(
    competitor_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_available = True
    consume_entered = asyncio.Event()
    release_consume = asyncio.Event()
    consume_calls: list[tuple[str, str | None]] = []
    credit = _credit("credit-1")
    redeem_lock = asyncio.Lock()

    @asynccontextmanager
    async def serialize(account_id: str, *, session: Any):
        async with redeem_lock:
            yield

    monkeypatch.setattr(reset_credits_api, "serialize_reset_credit_redeem", serialize)

    async def fetch_fn(*args: Any, **kwargs: Any) -> ResetCreditsResponse:
        if upstream_available:
            return _credits_response([credit])
        return _credits_response([], available_count=0)

    async def consume_fn(
        access_token: str,
        account_id: str | None,
        credit_id: str,
        **kwargs: Any,
    ) -> ConsumeResetCreditResponse:
        nonlocal upstream_available
        consume_calls.append((credit_id, kwargs.get("redeem_request_id")))
        consume_entered.set()
        await release_consume.wait()
        upstream_available = False
        return _consume_response(credit_id)

    store = RateLimitResetCreditsStore()
    await store.set("acc_rotation", reset_credits_api.build_snapshot(_credits_response([credit])))
    competitor_kwargs: dict[str, Any] = {}
    if competitor_kind == "automatic":
        competitor_kwargs = {
            "redeem_request_id": "auto-R",
            "skip_if_redeem_request_pinned": True,
            "expected_credit_id": credit.id,
            "expected_credit_expires_at": credit.expires_at,
        }

    competitor = asyncio.create_task(
        reset_credits_api._redeem_soonest_reset_credit(
            account=_account(),
            store=store,
            encryptor=StubEncryptor(),
            fetch_fn=fetch_fn,
            consume_fn=consume_fn,
            **competitor_kwargs,
        )
    )
    await consume_entered.wait()

    rotation = asyncio.create_task(
        resolve_rotation_reset_credit(
            _account(),
            redeem_request_id="rotation-R",
            observe_fresh_weekly=_observer([WeeklyRecoveryState.EXHAUSTED] * 3),
            refresh_usage=_noop_refresh,
            store=store,
            encryptor=StubEncryptor(),
            fetch_fn=fetch_fn,
            consume_fn=consume_fn,
            sleep_fn=_no_sleep,
        )
    )
    await asyncio.sleep(0)
    assert len(consume_calls) == 1

    release_consume.set()
    await competitor
    resolution = await rotation

    assert resolution.status is RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT
    assert len(consume_calls) == 1
