from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.refresh import RefreshError
from app.core.crypto import TokenEncryptor
from app.core.exceptions import AppError, DashboardConflictError
from app.core.upstream_proxy import ResolvedUpstreamRoute, UpstreamProxyRouteError
from app.db.models import Account
from app.db.session import get_background_session
from app.modules.accounts.auth_manager import AuthManager
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.rate_limit_reset_credits import api as reset_credits_api
from app.modules.rate_limit_reset_credits.redeem_coordination import get_pinned_redeem_credit_id
from app.modules.rate_limit_reset_credits.store import (
    RateLimitResetCreditsStore,
    get_rate_limit_reset_credits_store,
)

DEFAULT_RECONCILIATION_ATTEMPTS = 3
DEFAULT_RECONCILIATION_DELAY_SECONDS = 1.0


class WeeklyRecoveryState(StrEnum):
    """Semantic Weekly state supplied by the later G1 integration adapter.

    ``RECOVERED`` and ``EXHAUSTED`` are valid only for a fresh, classified
    Weekly observation for this exact account/member evaluation. Stale, failed,
    missing, mismatched, or unclassified P1 observations must be translated to
    ``UNKNOWN`` by the G1 adapter. P2 intentionally does not define or import
    the richer P1 observation DTO.
    """

    RECOVERED = "recovered"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class FreshWeeklyObserver(Protocol):
    async def __call__(self) -> WeeklyRecoveryState: ...


class UsageRefreshResult(Protocol):
    fetch_succeeded: bool


class RotationUsageRefresher(Protocol):
    async def force_refresh_result(self, account: Account) -> UsageRefreshResult: ...


class RotationResetCreditResolutionStatus(StrEnum):
    CONFIRMED_NO_REDEEMABLE_CREDIT = "confirmed_no_redeemable_credit"
    USAGE_RECOVERED = "usage_recovered"
    RECONCILIATION_PENDING = "reconciliation_pending"
    UNAVAILABLE = "unavailable"


class RotationResetCreditRedeemEvidence(StrEnum):
    NOT_ADMITTED = "not_admitted"
    DURABLY_PINNED = "durably_pinned"
    RESPONSE_RECEIVED = "response_received"


@dataclass(frozen=True, slots=True)
class RotationResetCreditResolution:
    status: RotationResetCreditResolutionStatus
    redeem_request_id: str
    account_id: str
    workspace_account_id: str | None
    redeem_evidence: RotationResetCreditRedeemEvidence = RotationResetCreditRedeemEvidence.NOT_ADMITTED
    selected_credit_id: str | None = None
    response_code: str | None = None
    windows_reset: int | None = None
    observations: tuple[WeeklyRecoveryState, ...] = ()
    error_code: str | None = None

    @property
    def redeem_admitted(self) -> bool:
        return self.redeem_evidence is not RotationResetCreditRedeemEvidence.NOT_ADMITTED


@dataclass(frozen=True, slots=True)
class _ReconciliationSeed:
    redeem_evidence: RotationResetCreditRedeemEvidence
    selected_credit_id: str | None = None
    response_code: str | None = None
    windows_reset: int | None = None
    error_code: str | None = None


SleepFn = Callable[[float], Awaitable[None]]


def build_rotation_usage_refresh_callback(
    usage_refresher: RotationUsageRefresher,
) -> reset_credits_api.RefreshUsageFn:
    """Adapt the existing Usage refresher without confusing no-write with failure."""

    async def refresh(account: Account) -> None:
        result = await usage_refresher.force_refresh_result(account)
        if not result.fetch_succeeded:
            raise RuntimeError(f"Forced usage refresh did not complete for account {account.id}")
        get_account_selection_cache().invalidate()

    return refresh


async def _default_resolve_route(account: Account) -> ResolvedUpstreamRoute | None:
    return await reset_credits_api._resolve_reset_credit_route(account)


async def resolve_rotation_reset_credit(
    account: Account,
    *,
    redeem_request_id: str,
    observe_fresh_weekly: FreshWeeklyObserver,
    refresh_usage: reset_credits_api.RefreshUsageFn,
    store: RateLimitResetCreditsStore | None = None,
    encryptor: TokenEncryptor | None = None,
    auth_manager: AuthManager | None = None,
    resolve_route: reset_credits_api.ResolveRouteFn | None = None,
    fetch_fn: reset_credits_api.FetchFn | None = None,
    consume_fn: reset_credits_api.ConsumeFn | None = None,
    sleep_fn: SleepFn = asyncio.sleep,
) -> RotationResetCreditResolution:
    """Resolve a reset opportunity for one already-exhausted rotation evaluation.

    The existing reset-credit authority remains the only redemption executor.
    This adapter changes only its admission evidence: rotation may proceed past
    an empty process-local snapshot so the serialized section can make a fresh
    authoritative detail read. Once a request is durably pinned, this function
    never issues that request upstream again; it switches to read-only Weekly
    reconciliation instead. P2 owns a short-lived database coordination session
    around the central redeem call so PostgreSQL advisory transaction locks and
    SQLite claims are released before bounded Weekly reconciliation begins.

    ``RECONCILIATION_PENDING`` is terminal for this exhausted-member evaluation:
    G1 must not call the resolver again merely to clear ambiguity or consume a
    second credit. A later independent evaluation uses its own request identity.
    """
    if not redeem_request_id.strip():
        raise ValueError("redeem_request_id must not be empty")

    effective_store = store or get_rate_limit_reset_credits_store()
    effective_encryptor = encryptor or TokenEncryptor()
    effective_resolve_route = resolve_route or _default_resolve_route

    async with get_background_session() as coordination_session:
        _assert_cross_replica_coordination_session(coordination_session)
        authority_result = await _resolve_authority_once(
            account=account,
            redeem_request_id=redeem_request_id,
            coordination_session=coordination_session,
            store=effective_store,
            encryptor=effective_encryptor,
            auth_manager=auth_manager,
            refresh_usage=refresh_usage,
            resolve_route=effective_resolve_route,
            fetch_fn=fetch_fn,
            consume_fn=consume_fn,
        )

    if isinstance(authority_result, RotationResetCreditResolution):
        return authority_result
    return await _reconcile_weekly_recovery(
        account_id=account.id,
        workspace_account_id=account.chatgpt_account_id,
        redeem_request_id=redeem_request_id,
        observe_fresh_weekly=observe_fresh_weekly,
        redeem_evidence=authority_result.redeem_evidence,
        selected_credit_id=authority_result.selected_credit_id,
        response_code=authority_result.response_code,
        windows_reset=authority_result.windows_reset,
        error_code=authority_result.error_code,
        sleep_fn=sleep_fn,
    )


def _assert_cross_replica_coordination_session(session: AsyncSession) -> None:
    dialect = session.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise ValueError(f"unsupported reset-credit coordination dialect: {dialect}")


async def _resolve_authority_once(
    *,
    account: Account,
    redeem_request_id: str,
    coordination_session: AsyncSession,
    store: RateLimitResetCreditsStore,
    encryptor: TokenEncryptor,
    auth_manager: AuthManager | None,
    refresh_usage: reset_credits_api.RefreshUsageFn,
    resolve_route: reset_credits_api.ResolveRouteFn | None,
    fetch_fn: reset_credits_api.FetchFn | None,
    consume_fn: reset_credits_api.ConsumeFn | None,
) -> RotationResetCreditResolution | _ReconciliationSeed:
    try:
        outcome = await reset_credits_api._redeem_soonest_reset_credit(
            account=account,
            store=store,
            encryptor=encryptor,
            lock_session=coordination_session,
            fetch_fn=fetch_fn,
            consume_fn=consume_fn,
            auth_manager=auth_manager,
            refresh_usage=refresh_usage,
            resolve_route=resolve_route,
            redeem_request_id=redeem_request_id,
            skip_if_redeem_request_pinned=True,
            allow_fresh_discovery=True,
        )
    except reset_credits_api.ResetCreditRedeemRequestAlreadyPinned as exc:
        return _ReconciliationSeed(
            redeem_evidence=RotationResetCreditRedeemEvidence.DURABLY_PINNED,
            selected_credit_id=exc.credit_id,
        )
    except DashboardConflictError as exc:
        if exc.code == "no_available_reset_credit":
            return RotationResetCreditResolution(
                status=RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT,
                redeem_request_id=redeem_request_id,
                account_id=account.id,
                workspace_account_id=account.chatgpt_account_id,
            )
        if exc.code == "reset_credit_redeem_in_progress":
            return _ReconciliationSeed(
                redeem_evidence=RotationResetCreditRedeemEvidence.NOT_ADMITTED,
                error_code=exc.code,
            )
        return await _authority_error_seed_or_unavailable(
            account_id=account.id,
            workspace_account_id=account.chatgpt_account_id,
            redeem_request_id=redeem_request_id,
            error_code=exc.code,
        )
    except (AppError, RefreshError, UpstreamProxyRouteError) as exc:
        return await _authority_error_seed_or_unavailable(
            account_id=account.id,
            workspace_account_id=account.chatgpt_account_id,
            redeem_request_id=redeem_request_id,
            error_code=getattr(exc, "code", type(exc).__name__),
        )
    return _ReconciliationSeed(
        redeem_evidence=RotationResetCreditRedeemEvidence.RESPONSE_RECEIVED,
        selected_credit_id=outcome.credit_id,
        response_code=outcome.response.code,
        windows_reset=outcome.response.windows_reset,
    )


async def _authority_error_seed_or_unavailable(
    *,
    account_id: str,
    workspace_account_id: str | None,
    redeem_request_id: str,
    error_code: str,
) -> RotationResetCreditResolution | _ReconciliationSeed:
    try:
        pinned_credit_id = await get_pinned_redeem_credit_id(account_id, redeem_request_id)
    except Exception:
        return RotationResetCreditResolution(
            status=RotationResetCreditResolutionStatus.UNAVAILABLE,
            redeem_request_id=redeem_request_id,
            account_id=account_id,
            workspace_account_id=workspace_account_id,
            error_code=error_code,
        )
    if pinned_credit_id is None:
        return RotationResetCreditResolution(
            status=RotationResetCreditResolutionStatus.UNAVAILABLE,
            redeem_request_id=redeem_request_id,
            account_id=account_id,
            workspace_account_id=workspace_account_id,
            error_code=error_code,
        )
    return _ReconciliationSeed(
        selected_credit_id=pinned_credit_id,
        redeem_evidence=RotationResetCreditRedeemEvidence.DURABLY_PINNED,
        error_code=error_code,
    )


async def _reconcile_weekly_recovery(
    *,
    account_id: str,
    workspace_account_id: str | None,
    redeem_request_id: str,
    observe_fresh_weekly: FreshWeeklyObserver,
    redeem_evidence: RotationResetCreditRedeemEvidence,
    sleep_fn: SleepFn,
    selected_credit_id: str | None = None,
    response_code: str | None = None,
    windows_reset: int | None = None,
    error_code: str | None = None,
) -> RotationResetCreditResolution:
    observations: list[WeeklyRecoveryState] = []
    for attempt in range(DEFAULT_RECONCILIATION_ATTEMPTS):
        try:
            observation = await observe_fresh_weekly()
        except Exception:
            observation = WeeklyRecoveryState.UNKNOWN
        observations.append(observation)
        if observation is WeeklyRecoveryState.RECOVERED:
            return RotationResetCreditResolution(
                status=RotationResetCreditResolutionStatus.USAGE_RECOVERED,
                redeem_request_id=redeem_request_id,
                account_id=account_id,
                workspace_account_id=workspace_account_id,
                redeem_evidence=redeem_evidence,
                selected_credit_id=selected_credit_id,
                response_code=response_code,
                windows_reset=windows_reset,
                observations=tuple(observations),
                error_code=error_code,
            )
        if attempt + 1 < DEFAULT_RECONCILIATION_ATTEMPTS:
            await sleep_fn(DEFAULT_RECONCILIATION_DELAY_SECONDS)

    return RotationResetCreditResolution(
        status=RotationResetCreditResolutionStatus.RECONCILIATION_PENDING,
        redeem_request_id=redeem_request_id,
        account_id=account_id,
        workspace_account_id=workspace_account_id,
        redeem_evidence=redeem_evidence,
        selected_credit_id=selected_credit_id,
        response_code=response_code,
        windows_reset=windows_reset,
        observations=tuple(observations),
        error_code=error_code,
    )
