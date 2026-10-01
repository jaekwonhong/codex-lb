"""Read-only admission advice for an already proof-checked continuation.

This module never changes affinity, acquires a lease, sends a request, refreshes
tokens or writes account health. Its result is advisory: the ordinary selector
still revalidates policy and capacity atomically when the replacement is admitted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timezone
from typing import TYPE_CHECKING, Literal, cast

from app.core.balancer import AccountState, RoutingStrategy, select_account
from app.core.balancer.recovery import OwnerRecoveryHint
from app.core.config.dashboard_overrides import with_dashboard_overrides
from app.core.config.settings import get_settings
from app.core.resilience.toggles import resolve_resilience_toggles
from app.db.models import AccountStatus, DashboardSettings
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy._load_balancer.opportunistic_admission import detached_runtime_snapshot
from app.modules.proxy._load_balancer.sticky_selection import _select_account_preferring_budget_safe
from app.modules.proxy._load_balancer.tunables import account_lease_stale_ttl_seconds
from app.modules.proxy._load_balancer.types import RuntimeState

if TYPE_CHECKING:
    from app.modules.proxy._service.support import _WebSocketRequestState
    from app.modules.proxy.load_balancer import LoadBalancer


@dataclass(frozen=True, slots=True)
class OwnerRecoveryAdvice:
    owner_id: str
    hint: OwnerRecoveryHint
    alternate_id: str | None


def turn_is_unsubmitted(state: _WebSocketRequestState) -> bool:
    """Absence of output alone is not proof that replay is safe."""
    return (
        state.response_create_sent_at is None
        and state.response_create_attempt_count == 0
        and state.response_create_attempt is None
        and state.response_id is None
        and state.response_event_count == 0
        # awaiting_response_created is set at preparation, before any send.
        # Only the attempt/sent markers above prove the dispatch boundary.
        and state.last_downstream_sequence_number is None
        and not state.downstream_visible
        and not state.operation_registered
        and not state.operation_dispatched
        and not state.recovery_attempt_dispatched
        and state.operation_persisted_response_id is None
        and state.replay_downstream_response_id is None
        and not state.payload_conversation_bound
        and state.request_kind == "normal"
    )


def owner_pressure_hint(
    state: AccountState,
    *,
    now: float,
    primary_threshold: float,
    secondary_threshold: float,
    fresh_usage: bool,
) -> OwnerRecoveryHint | None:
    if state.status in (AccountStatus.PAUSED, AccountStatus.DEACTIVATED):
        return OwnerRecoveryHint("unavailable")
    if state.status == AccountStatus.REAUTH_REQUIRED:
        # Warning-only credentials may still be routable; do not conflate the
        # need to refresh eventually with an unusable current access token.
        if state.access_token_expires_at is not None and state.access_token_expires_at <= now:
            return OwnerRecoveryHint("unavailable")
    if not state.ignore_standard_quota and state.status in (AccountStatus.RATE_LIMITED, AccountStatus.QUOTA_EXCEEDED):
        if state.reset_at is None or state.reset_at > now:
            reason: Literal["quota_exhausted", "cooldown"] = (
                "quota_exhausted" if state.status == AccountStatus.QUOTA_EXCEEDED else "cooldown"
            )
            primary_used = (
                state.priority_used_percent if state.priority_used_percent is not None else state.used_percent
            )
            secondary_used = (
                state.priority_secondary_used_percent
                if state.priority_secondary_used_percent is not None
                else state.secondary_used_percent
            )
            primary_exhausted = fresh_usage and (primary_used or 0) >= 100
            secondary_exhausted = fresh_usage and (secondary_used or 0) >= 100
            if primary_exhausted or secondary_exhausted:
                reason = "quota_exhausted"
            # A local 30-second admission hold is not the quota reset. Preserve
            # the applicable exhausted window even before that hold expires.
            deadline = (
                max(
                    state.reset_at or 0.0,
                    state.cooldown_until or 0.0,
                    (state.primary_reset_at or 0.0) if primary_exhausted else 0.0,
                    (state.secondary_reset_at or 0.0) if secondary_exhausted else 0.0,
                )
                or None
            )
            return OwnerRecoveryHint(reason, deadline)
    if state.cooldown_until is not None and state.cooldown_until > now:
        return OwnerRecoveryHint("cooldown", state.cooldown_until)
    if (
        fresh_usage
        and not state.ignore_standard_quota
        and (
            (state.used_percent is not None and state.used_percent > primary_threshold)
            or (state.secondary_used_percent is not None and state.secondary_used_percent > secondary_threshold)
        )
    ):
        return OwnerRecoveryHint("headroom")
    return None


async def assess_owner_recovery(
    owner: LoadBalancer,
    *,
    owner_id: str,
    model: str,
    service_tier: str | None,
    api_key: ApiKeyData | None,
    dashboard: DashboardSettings,
    excluded_account_ids: set[str],
    estimated_tokens: float = 0.0,
    require_security_work_authorized: bool = False,
) -> OwnerRecoveryAdvice | None:
    # Keep operator-chosen drain/single-account semantics and opportunistic
    # admission out of this foreground optimization.
    routing_strategy = getattr(dashboard, "routing_strategy", None)
    if routing_strategy is None or routing_strategy in ("single_account", "sequential_drain", "reset_drain"):
        # Missing operator-policy evidence cannot authorize an optimization.
        # The ordinary route remains authoritative for partial collaborators.
        return None
    if api_key is not None and api_key.traffic_class == "opportunistic":
        return None
    scope = set(api_key.assigned_account_ids) if api_key and api_key.account_assignment_scope_enabled else None
    if owner_id in excluded_account_ids or (scope is not None and owner_id not in scope):
        return None

    # Local import avoids making the selection core depend on this optional
    # transport-level advice. Reuse its exact model/quota normalization.
    from app.modules.proxy.load_balancer import (
        _build_states,
        _extract_credit_status,
        _usage_entry_is_recent_enough,
        effective_account_concurrency_caps,
        effective_routing_tunables,
    )

    inputs = await owner._load_selection_inputs(
        model=model,
        service_tier=service_tier,
        additional_limit_name=None,
        account_ids=scope,
    )
    if inputs.error_code is not None or owner_id not in {
        account.id for account in inputs.effective_continuity_owner_candidates
    }:
        return None
    accounts = [account for account in inputs.accounts if account.id not in excluded_account_ids]
    if require_security_work_authorized:
        accounts = [account for account in accounts if account.security_work_authorized]
    if owner_id not in {account.id for account in accounts}:
        return None
    tunables = effective_routing_tunables(dashboard)
    caps = effective_account_concurrency_caps(dashboard)
    runtime_settings = with_dashboard_overrides(get_settings())
    async with owner._runtime_lock:
        now = owner._clock.time()
        runtime = detached_runtime_snapshot(
            owner._runtime,
            now=owner._clock.monotonic(),
            stale_lease_ttl_seconds=lambda kind: account_lease_stale_ttl_seconds(
                kind, runtime_settings, routing_tunables=tunables
            ),
        )
        # Candidate pressure includes already leased work plus this request's
        # existing estimate. No assertion that subscription credits equal tokens.
        for account in accounts:
            runtime.setdefault(account.id, RuntimeState()).leased_tokens += max(0.0, estimated_tokens)
        capacity_ids = {
            account.id
            for account in accounts
            if caps.stream_limit <= 0 or runtime[account.id].inflight_streams < caps.stream_limit
        }
    states, _ = _build_states(
        accounts=accounts,
        latest_primary=inputs.latest_primary,
        latest_secondary=inputs.latest_secondary,
        latest_monthly=inputs.latest_monthly,
        runtime=runtime,
        now=now,
        routing_policy_override=inputs.routing_policy_override,
        ignore_standard_quota_account_ids=inputs.ignore_standard_quota_account_ids,
        encryptor=owner._encryptor,
        routing_tunables=tunables,
        soft_drain_enabled=resolve_resilience_toggles(dashboard).soft_drain_enabled,
        model=model,
        log_weight_transitions=False,
    )
    primary_threshold = dashboard.sticky_reallocation_primary_budget_threshold_pct
    secondary_threshold = dashboard.sticky_reallocation_secondary_budget_threshold_pct
    if primary_threshold is None:
        primary_threshold = dashboard.sticky_reallocation_budget_threshold_pct
    primary_threshold = 95.0 if primary_threshold is None else primary_threshold
    secondary_threshold = 100.0 if secondary_threshold is None else secondary_threshold

    def hint(state: AccountState) -> OwnerRecoveryHint | None:
        entries = [
            inputs.latest_primary.get(state.account_id),
            inputs.latest_secondary.get(state.account_id),
            inputs.latest_monthly.get(state.account_id),
        ]
        # Both reported windows must be fresh before percentages drive a move.
        reported = [entry for entry in entries if entry is not None]
        fresh = bool(reported) and all(
            entry.recorded_at is not None
            and _usage_entry_is_recent_enough(entry.recorded_at, now=now)
            and (
                entry.recorded_at if entry.recorded_at.tzinfo else entry.recorded_at.replace(tzinfo=timezone.utc)
            ).timestamp()
            <= now
            for entry in reported
        )
        credits_has, credits_unlimited, credits_balance = _extract_credit_status(*entries)
        pressure_state = replace(state)
        if credits_has or credits_unlimited or (credits_balance or 0) > 0:
            # Preserve the selector's established credit override for the long
            # window; this optimization never activates paid capacity itself.
            pressure_state.secondary_used_percent = None
            pressure_state.priority_secondary_used_percent = None
        return owner_pressure_hint(
            pressure_state,
            now=now,
            primary_threshold=primary_threshold,
            secondary_threshold=secondary_threshold,
            fresh_usage=fresh,
        )

    owner_state = next((state for state in states if state.account_id == owner_id), None)
    if owner_state is None or (owner_hint := hint(owner_state)) is None:
        return None
    alternatives = [
        replace(state)
        for state in states
        if state.account_id != owner_id
        and state.account_id in capacity_ids
        and hint(state) is None
        and select_account([replace(state)], now=now, allow_backoff_fallback=False).account is not None
    ]
    selection = _select_account_preferring_budget_safe(
        alternatives,
        prefer_earlier_reset=dashboard.prefer_earlier_reset_accounts,
        prefer_earlier_reset_window="primary" if dashboard.prefer_earlier_reset_window == "primary" else "secondary",
        routing_strategy=cast(RoutingStrategy, routing_strategy),
        relative_availability_power=dashboard.relative_availability_power,
        relative_availability_top_k=dashboard.relative_availability_top_k,
        budget_threshold_pct=primary_threshold,
        secondary_budget_threshold_pct=secondary_threshold,
        apply_secondary_budget_threshold=True,
        allow_backoff_fallback=False,
        now=now,
    )
    return OwnerRecoveryAdvice(owner_id, owner_hint, selection.account.account_id if selection.account else None)
