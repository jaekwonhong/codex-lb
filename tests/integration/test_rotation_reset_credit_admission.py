from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.clients.rate_limit_reset_credits import (
    ConsumeResetCreditCredit,
    ConsumeResetCreditError,
    ConsumeResetCreditResponse,
    ResetCreditItem,
    ResetCreditsResponse,
    build_snapshot,
)
from app.core.crypto import TokenEncryptor
from app.core.exceptions import DashboardConflictError, DashboardPermissionError
from app.db.models import Account, AccountStatus, ResetCreditRedeemClaim
from app.db.session import SessionLocal
from app.modules.accounts.auth_manager import AuthManager
from app.modules.rate_limit_reset_credits import api as reset_credits_api
from app.modules.rate_limit_reset_credits.redeem_coordination import (
    RedeemClaimTimeoutError,
    get_pinned_redeem_credit_id,
    pin_redeem_request,
)
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditRedeemEvidence,
    RotationResetCreditResolution,
    RotationResetCreditResolutionStatus,
    WeeklyRecoveryState,
    resolve_rotation_reset_credit,
)
from app.modules.rate_limit_reset_credits.store import RateLimitResetCreditsStore

pytestmark = pytest.mark.integration
REQUEST_ID = "rotation-admission-R"


class StubEncryptor(TokenEncryptor):
    def __init__(self) -> None:
        pass

    def decrypt(self, encrypted: bytes) -> str:
        return "test-access-token"


def _account() -> Account:
    return Account(
        id="acc-admission",
        chatgpt_account_id="workspace-admission",
        chatgpt_user_id="user-admission",
        email="admission@example.com",
        plan_type="business",
        access_token_encrypted=b"test-access",
        refresh_token_encrypted=b"test-refresh",
        id_token_encrypted=b"test-id",
        last_refresh=datetime(2026, 9, 22),
        status=AccountStatus.ACTIVE,
    )


def _credits() -> ResetCreditsResponse:
    return ResetCreditsResponse(
        available_count=2,
        credits=[
            ResetCreditItem(id="credit-1", status="available", expires_at=datetime(2030, 1, 1, tzinfo=UTC)),
            ResetCreditItem(id="credit-2", status="available", expires_at=datetime(2030, 2, 1, tzinfo=UTC)),
        ],
    )


def _consumed() -> ConsumeResetCreditResponse:
    return ConsumeResetCreditResponse(
        code="reset",
        credit=ConsumeResetCreditCredit(
            id="credit-1", status="redeemed", redeemed_at=datetime(2026, 9, 22, tzinfo=UTC)
        ),
        windows_reset=1,
    )


@pytest.fixture
async def reset_account(_reset_db_state: bool) -> Account:
    account = _account()
    async with SessionLocal() as session:
        session.add(account)
        await session.commit()
        session.expunge(account)
    return account


@dataclass
class ResetCalls:
    fetch: AsyncMock
    consume: AsyncMock
    refresh: AsyncMock
    observe: AsyncMock


@pytest.fixture
def calls() -> ResetCalls:
    return ResetCalls(
        fetch=AsyncMock(return_value=_credits()),
        consume=AsyncMock(return_value=_consumed()),
        refresh=AsyncMock(),
        observe=AsyncMock(return_value=WeeklyRecoveryState.EXHAUSTED),
    )


async def _direct_route(account: Account) -> None:
    return None


async def _no_sleep(seconds: float) -> None:
    return None


async def _resolve(
    account: Account,
    calls: ResetCalls,
    *,
    before_consume: reset_credits_api.BeforeConsumeFn | None = None,
    auth_manager: AuthManager | None = None,
) -> RotationResetCreditResolution:
    return await resolve_rotation_reset_credit(
        account,
        redeem_request_id=REQUEST_ID,
        observe_fresh_weekly=calls.observe,
        refresh_usage=calls.refresh,
        store=RateLimitResetCreditsStore(),
        encryptor=StubEncryptor(),
        auth_manager=auth_manager,
        fetch_fn=calls.fetch,
        consume_fn=calls.consume,
        resolve_route=_direct_route,
        before_consume=before_consume,
        sleep_fn=_no_sleep,
    )


async def _assert_pin_preserved_and_claim_released(account: Account) -> None:
    # Independent sessions observe the committed pin after resolver cleanup.
    assert await get_pinned_redeem_credit_id(account.id, REQUEST_ID) == "credit-1"
    async with SessionLocal() as session:
        claim = await session.scalar(
            select(ResetCreditRedeemClaim).where(ResetCreditRedeemClaim.account_id == account.id)
        )
    assert claim is None


@pytest.mark.asyncio
@pytest.mark.parametrize("already_pinned", [False, True], ids=["no-credit", "already-pinned"])
async def test_no_consume_path_does_not_call_admission(
    reset_account: Account, calls: ResetCalls, already_pinned: bool
) -> None:
    if already_pinned:
        await pin_redeem_request(reset_account.id, REQUEST_ID, "credit-1")
    else:
        calls.fetch.return_value = ResetCreditsResponse(available_count=0, credits=[])
    admission = AsyncMock(side_effect=AssertionError("non-consume path requested admission"))

    result = await _resolve(reset_account, calls, before_consume=admission)

    admission.assert_not_awaited()
    calls.consume.assert_not_awaited()
    calls.refresh.assert_not_awaited()
    if already_pinned:
        calls.fetch.assert_not_awaited()
        assert result.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
        assert result.redeem_evidence is RotationResetCreditRedeemEvidence.DURABLY_PINNED
        await _assert_pin_preserved_and_claim_released(reset_account)
    else:
        calls.fetch.assert_awaited_once()
        calls.observe.assert_not_awaited()
        assert result.status is RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT
        assert await get_pinned_redeem_credit_id(reset_account.id, REQUEST_ID) is None


@pytest.mark.asyncio
async def test_admission_receives_refreshed_account_after_pin_immediately_before_consume(
    reset_account: Account, calls: ResetCalls, monkeypatch: pytest.MonkeyPatch
) -> None:
    refreshed_account = _account()
    refreshed_account.access_token_encrypted = b"refreshed-test-access"
    auth_manager = AsyncMock(spec=AuthManager)
    auth_manager.ensure_fresh.return_value = refreshed_account
    events: list[str] = []

    async def delayed_pin(account_id: str, request_id: str, credit_id: str) -> str:
        pinned = await pin_redeem_request(account_id, request_id, credit_id)
        await asyncio.sleep(0)
        events.append("pin-committed")
        return pinned

    async def admit(account: Account) -> None:
        assert account is refreshed_account
        calls.fetch.assert_awaited_once()
        assert await get_pinned_redeem_credit_id(account.id, REQUEST_ID) == "credit-1"
        assert events == ["pin-committed"]
        events.append("admitted")
        # Any event-loop suspension before entering consume would run this first.
        asyncio.get_running_loop().call_soon(events.append, "yielded")

    async def consume(
        access_token: str, workspace_account_id: str | None, credit_id: str, **kwargs: object
    ) -> ConsumeResetCreditResponse:
        assert events == ["pin-committed", "admitted"]
        assert workspace_account_id == refreshed_account.chatgpt_account_id
        assert credit_id == "credit-1"
        events.append("consume")
        return _consumed()

    monkeypatch.setattr(reset_credits_api, "pin_redeem_request", delayed_pin)
    calls.consume.side_effect = consume
    calls.observe.return_value = WeeklyRecoveryState.RECOVERED

    result = await _resolve(reset_account, calls, before_consume=admit, auth_manager=cast(AuthManager, auth_manager))

    auth_manager.ensure_fresh.assert_awaited_once_with(reset_account, force=False)
    calls.consume.assert_awaited_once()
    calls.refresh.assert_awaited_once_with(refreshed_account)
    assert events[:3] == ["pin-committed", "admitted", "consume"]
    assert result.status is RotationResetCreditResolutionStatus.USAGE_RECOVERED
    assert result.redeem_evidence is RotationResetCreditRedeemEvidence.RESPONSE_RECEIVED
    await _assert_pin_preserved_and_claim_released(reset_account)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        ValueError("rotation_workspace_disabled"),
        DashboardConflictError("admission denied", code="no_available_reset_credit"),
        DashboardConflictError("admission denied", code="reset_credit_redeem_in_progress"),
        DashboardPermissionError("admission denied"),
        ConsumeResetCreditError(503, "admission denied", code="guard_failed"),
        RedeemClaimTimeoutError("admission denied"),
    ],
    ids=["plan-denial", "no-credit-code", "claim-code", "domain-error", "consume-error", "claim-error"],
)
async def test_admission_error_propagates_with_durable_pin_and_retry_never_replays(
    reset_account: Account, calls: ResetCalls, failure: Exception
) -> None:
    calls.observe.return_value = WeeklyRecoveryState.RECOVERED

    async def reject(account: Account) -> None:
        calls.fetch.assert_awaited_once()
        assert await get_pinned_redeem_credit_id(account.id, REQUEST_ID) == "credit-1"
        raise failure

    with pytest.raises(type(failure)) as rejected:
        await _resolve(reset_account, calls, before_consume=reject)

    assert rejected.value is failure
    calls.consume.assert_not_awaited()
    calls.refresh.assert_not_awaited()
    calls.observe.assert_not_awaited()
    await _assert_pin_preserved_and_claim_released(reset_account)

    calls.observe.return_value = WeeklyRecoveryState.EXHAUSTED
    retry_admission = AsyncMock(side_effect=AssertionError("pinned retry must not request admission"))
    retry = await _resolve(reset_account, calls, before_consume=retry_admission)

    retry_admission.assert_not_awaited()
    calls.fetch.assert_awaited_once()
    calls.consume.assert_not_awaited()
    calls.refresh.assert_not_awaited()
    assert calls.observe.await_count == 3
    assert retry.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    assert retry.redeem_evidence is RotationResetCreditRedeemEvidence.DURABLY_PINNED
    assert retry.selected_credit_id == "credit-1"
    await _assert_pin_preserved_and_claim_released(reset_account)


@pytest.mark.asyncio
async def test_cancellation_during_admission_preserves_pin_and_releases_claim(
    reset_account: Account, calls: ResetCalls
) -> None:
    admission_entered = asyncio.Event()

    async def admit(account: Account) -> None:
        assert await get_pinned_redeem_credit_id(account.id, REQUEST_ID) == "credit-1"
        admission_entered.set()
        await asyncio.Event().wait()

    attempt = asyncio.create_task(_resolve(reset_account, calls, before_consume=admit))
    try:
        await asyncio.wait_for(admission_entered.wait(), timeout=5)
        attempt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attempt
    finally:
        attempt.cancel()
        with suppress(asyncio.CancelledError):
            await attempt

    calls.consume.assert_not_awaited()
    calls.refresh.assert_not_awaited()
    calls.observe.assert_not_awaited()
    await _assert_pin_preserved_and_claim_released(reset_account)

    retry_admission = AsyncMock(side_effect=AssertionError("cancelled attempt must not be replayed"))
    retry = await _resolve(reset_account, calls, before_consume=retry_admission)
    retry_admission.assert_not_awaited()
    calls.fetch.assert_awaited_once()
    calls.consume.assert_not_awaited()
    assert retry.status is RotationResetCreditResolutionStatus.RECONCILIATION_PENDING
    await _assert_pin_preserved_and_claim_released(reset_account)


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [None, "ordinary-R"], ids=["generated-id", "caller-id"])
async def test_ordinary_central_caller_without_hook_still_consumes_once(
    reset_account: Account, calls: ResetCalls, request_id: str | None
) -> None:
    store = RateLimitResetCreditsStore()
    await store.set(reset_account.id, build_snapshot(_credits()))
    async with SessionLocal() as session:
        result = await reset_credits_api._redeem_soonest_reset_credit(
            account=reset_account,
            store=store,
            encryptor=StubEncryptor(),
            lock_session=session,
            fetch_fn=calls.fetch,
            consume_fn=calls.consume,
            redeem_request_id=request_id,
        )

    calls.fetch.assert_awaited_once()
    calls.consume.assert_awaited_once()
    assert result.response.code == "reset"
    assert result.credit_id == "credit-1"
    assert calls.consume.await_args is not None
    actual_request_id = calls.consume.await_args.kwargs["redeem_request_id"]
    assert isinstance(actual_request_id, str) and actual_request_id
    if request_id is not None:
        assert actual_request_id == request_id
    assert await get_pinned_redeem_credit_id(reset_account.id, actual_request_id) == "credit-1"
