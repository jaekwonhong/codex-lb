from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from app.core import usage as usage_core
from app.core.auth.api_key_cache import get_api_key_cache
from app.db.models import Account, AccountStatus, UsageHistory
from app.modules.member_auth_handoff.catalog import (
    PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    MemberAuthHandoffCatalog,
    MemberAuthHandoffCatalogRegistry,
)
from app.modules.member_auth_handoff.schemas import (
    CatalogMemberRegistrationRequest,
    CatalogMemberRegistrationResponse,
    CatalogMemberUsage,
    CatalogMemberUsageResponse,
    HandoffState,
    MemberAuthHandoffPrepareRequest,
    MemberAuthHandoffResponse,
    MemberAuthReconciliationRequest,
    MemberAuthReconciliationResponse,
    MemberAuthUsageSnapshot,
    WorkspaceAuthObservationMember,
    WorkspaceAuthObservationResponse,
)
from app.modules.oauth.schemas import OauthStartRequest, OauthStartResponse, OauthStatusResponse
from app.modules.proxy.account_cache import (
    get_account_selection_cache,
    mark_account_routing_unavailable,
    propagate_account_routing_change,
)

_QUARANTINE_REASON = "member_auth_handoff_quarantine"
_DEVICE_CODE_EXPIRED_MESSAGE = "Device code expired."
_MAX_DEVICE_CODE_REISSUES = 1
_OPENAI_AVERAGE_MONTH_WINDOW_MINUTES = 43_800
_AUTHENTICATED_STATUSES = {
    AccountStatus.ACTIVE,
    AccountStatus.RATE_LIMITED,
    AccountStatus.QUOTA_EXCEEDED,
}


class AccountsRepositoryPort(Protocol):
    async def list_accounts(self, *, refresh_existing: bool = False) -> list[Account]: ...

    async def update_status(
        self,
        account_id: str,
        status: AccountStatus,
        deactivation_reason: str | None = None,
        reset_at: int | None = None,
        blocked_at: int | None | object = ...,
    ) -> bool: ...

    async def delete(self, account_id: str, *, delete_history: bool = False) -> bool: ...


class OauthServicePort(Protocol):
    async def start_oauth(self, request: OauthStartRequest) -> OauthStartResponse: ...

    async def oauth_status(self, flow_id: str | None = None) -> OauthStatusResponse: ...

    async def current_device_flow_id(self) -> str | None: ...


class UsageRepositoryPort(Protocol):
    async def latest_entry_for_account(
        self,
        account_id: str,
        *,
        window: str | None = None,
    ) -> UsageHistory | None: ...


@dataclass(slots=True)
class _Handoff:
    handoff_id: str
    request: MemberAuthHandoffPrepareRequest
    state: HandoffState
    flow_id: str | None = None
    intended_account_id: str | None = None
    old_account_id: str | None = None
    old_account_email: str | None = None
    old_account_user_id: str | None = None
    removed_auth_usage_snapshot: MemberAuthUsageSnapshot | None = None
    verification_url: str | None = None
    user_code: str | None = None
    expires_in_seconds: int | None = None
    device_code_reissues: int = 0
    old_auth_deleted: bool = False
    error_code: str | None = None
    error_message: str | None = None


class MemberAuthHandoffStore:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.operations: dict[str, _Handoff] = {}


_HANDOFF_STORE = MemberAuthHandoffStore()


class MemberAuthHandoffService:
    def __init__(
        self,
        repository: AccountsRepositoryPort,
        oauth_service: OauthServicePort,
        store: MemberAuthHandoffStore = _HANDOFF_STORE,
        catalog: MemberAuthHandoffCatalog = PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
        usage_repository: UsageRepositoryPort | None = None,
        catalog_registry: MemberAuthHandoffCatalogRegistry | None = None,
        checkpoint: Callable[[_Handoff], Awaitable[None]] | None = None,
    ) -> None:
        self._repository = repository
        self._oauth = oauth_service
        self._store = store
        self._catalog = catalog
        self._usage = usage_repository
        self._catalog_registry = catalog_registry
        self._checkpoint_callback = checkpoint

    async def _checkpoint(self, handoff: _Handoff) -> None:
        if self._checkpoint_callback is not None:
            await self._checkpoint_callback(handoff)

    def register_catalog_member(
        self,
        request: CatalogMemberRegistrationRequest,
    ) -> CatalogMemberRegistrationResponse:
        if self._catalog_registry is None:
            raise RuntimeError("Member auth catalog overlay is not configured.")
        return self._catalog_registry.register(request)

    async def reconcile_auth(
        self,
        request: MemberAuthReconciliationRequest,
    ) -> MemberAuthReconciliationResponse:
        async with self._store.lock:
            catalog = self._catalog_snapshot()
            if request.catalog_fingerprint != catalog.fingerprint():
                return MemberAuthReconciliationResponse(
                    accepted=False,
                    code="catalog_mismatch",
                    action=request.action,
                )
            target_mapping = catalog.find_target(
                preset_id=request.preset_id,
                email=request.target_email,
                user_id=request.target_user_id,
            )
            if (
                target_mapping is None
                or target_mapping.workspace_id != request.workspace_id
                or target_mapping.workspace_account_id != request.workspace_account_id
            ):
                return MemberAuthReconciliationResponse(
                    accepted=False,
                    code="workspace_identity_mismatch",
                    action=request.action,
                )
            try:
                accounts = await self._repository.list_accounts(refresh_existing=True)
            except Exception:
                return MemberAuthReconciliationResponse(
                    accepted=False,
                    code="observation_unavailable",
                    action=request.action,
                )
            workspace_accounts = [
                account for account in accounts if account.chatgpt_account_id == request.workspace_account_id
            ]
            target_matches = self._matching_accounts(
                workspace_accounts,
                request.workspace_account_id,
                request.target_email,
                request.target_user_id,
            )
            if len(target_matches) > 1 or self._partial_identity_matches(
                workspace_accounts,
                request.target_email,
                request.target_user_id,
                target_matches,
            ):
                return MemberAuthReconciliationResponse(
                    accepted=False,
                    code="ambiguous_target_auth",
                    action=request.action,
                )
            if request.action == "cleanup_old_auth":
                if len(target_matches) != 1 or target_matches[0].status not in _AUTHENTICATED_STATUSES:
                    return MemberAuthReconciliationResponse(
                        accepted=False,
                        code="target_auth_not_active",
                        action=request.action,
                    )
                target_account = target_matches[0]
                old_matches = [
                    account
                    for account in workspace_accounts
                    if account.id != target_account.id
                    and account.status == AccountStatus.PAUSED
                    and account.deactivation_reason == _QUARANTINE_REASON
                    and catalog.contains_member(
                        workspace_id=request.workspace_id,
                        email=account.email,
                        user_id=account.chatgpt_user_id,
                    )
                ]
                if len(old_matches) > 1:
                    return MemberAuthReconciliationResponse(
                        accepted=False,
                        code="ambiguous_old_auth",
                        action=request.action,
                    )
                if not old_matches:
                    return MemberAuthReconciliationResponse(
                        accepted=True,
                        code="already_clean",
                        action=request.action,
                    )
                if not await self._repository.delete(old_matches[0].id):
                    return MemberAuthReconciliationResponse(
                        accepted=False,
                        code="old_auth_delete_failed",
                        action=request.action,
                    )
                get_account_selection_cache().invalidate()
                get_api_key_cache().clear()
                await propagate_account_routing_change()
                return MemberAuthReconciliationResponse(
                    accepted=True,
                    code="old_auth_deleted",
                    action=request.action,
                )
            if request.action == "unpause_target_auth":
                if not target_matches:
                    return MemberAuthReconciliationResponse(
                        accepted=False,
                        code="target_auth_absent",
                        action=request.action,
                    )
                target_account = target_matches[0]
                if target_account.status in _AUTHENTICATED_STATUSES:
                    return MemberAuthReconciliationResponse(
                        accepted=True,
                        code="already_active",
                        action=request.action,
                    )
                if (
                    target_account.status != AccountStatus.PAUSED
                    or target_account.deactivation_reason != _QUARANTINE_REASON
                ):
                    return MemberAuthReconciliationResponse(
                        accepted=False,
                        code="target_auth_quarantine_mismatch",
                        action=request.action,
                    )
                if not await self._repository.update_status(
                    target_account.id,
                    AccountStatus.ACTIVE,
                    None,
                    blocked_at=None,
                ):
                    return MemberAuthReconciliationResponse(
                        accepted=False,
                        code="target_auth_unpause_failed",
                        action=request.action,
                    )
                get_account_selection_cache().invalidate()
                get_api_key_cache().clear()
                await propagate_account_routing_change()
                return MemberAuthReconciliationResponse(
                    accepted=True,
                    code="target_auth_unpaused",
                    action=request.action,
                )
            return MemberAuthReconciliationResponse(
                accepted=False,
                code="reconciliation_action_unsupported",
                action=request.action,
            )

    def _catalog_snapshot(self) -> MemberAuthHandoffCatalog:
        if self._catalog_registry is not None:
            return self._catalog_registry.effective_catalog()
        return self._catalog

    async def observe_workspace_auth(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
    ) -> WorkspaceAuthObservationResponse:
        catalog = self._catalog_snapshot()
        fingerprint = catalog.fingerprint()
        entries = tuple(entry for entry in catalog.entries if entry.workspace_id == workspace_id)
        observed_at = datetime.now(timezone.utc)
        if not entries or any(entry.workspace_account_id != workspace_account_id for entry in entries):
            return WorkspaceAuthObservationResponse(
                available=False,
                code="workspace_account_unmapped",
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                catalog_fingerprint=fingerprint,
                observed_at=observed_at,
                refresh_available=False,
                active_auth_count=0,
                identity_ambiguous=False,
                members=[],
            )
        try:
            accounts = await self._repository.list_accounts(refresh_existing=True)
        except Exception:
            return WorkspaceAuthObservationResponse(
                available=False,
                code="observation_unavailable",
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                catalog_fingerprint=fingerprint,
                observed_at=observed_at,
                refresh_available=False,
                active_auth_count=0,
                identity_ambiguous=False,
                members=[],
            )

        workspace_accounts = [account for account in accounts if account.chatgpt_account_id == workspace_account_id]
        exact_catalog_identities = {(entry.email.casefold(), entry.user_id) for entry in entries}
        owner_email = entries[0].owner_email.casefold()
        unknown_active = any(
            account.status in _AUTHENTICATED_STATUSES
            and account.email.casefold() != owner_email
            and (account.email.casefold(), account.chatgpt_user_id) not in exact_catalog_identities
            for account in workspace_accounts
        )
        members: list[WorkspaceAuthObservationMember] = []
        identity_ambiguous = unknown_active
        for entry in entries:
            exact = self._matching_accounts(
                workspace_accounts,
                workspace_account_id,
                entry.email,
                entry.user_id,
            )
            partial = [
                account
                for account in workspace_accounts
                if (account.email.casefold() == entry.email.casefold() or account.chatgpt_user_id == entry.user_id)
                and account not in exact
            ]
            if len(exact) > 1 or partial:
                identity_ambiguous = True
                members.append(
                    WorkspaceAuthObservationMember(
                        preset_id=entry.preset_id,
                        email=entry.email,
                        user_id=entry.user_id,
                        state="ambiguous",
                    )
                )
                continue
            if not exact:
                members.append(
                    WorkspaceAuthObservationMember(
                        preset_id=entry.preset_id,
                        email=entry.email,
                        user_id=entry.user_id,
                        state="absent",
                    )
                )
                continue
            account = exact[0]
            if account.status in _AUTHENTICATED_STATUSES:
                state = "active"
            elif account.status == AccountStatus.PAUSED and account.deactivation_reason == _QUARANTINE_REASON:
                state = "handoff_quarantined"
            else:
                state = "inactive"
            usage_snapshot = await self._capture_removed_auth_usage(account.id) if state == "active" else None
            members.append(
                WorkspaceAuthObservationMember(
                    preset_id=entry.preset_id,
                    email=entry.email,
                    user_id=entry.user_id,
                    state=state,
                    auth_account_id=account.id,
                    auth_status=account.status.value,
                    deactivation_reason=account.deactivation_reason,
                    usage=usage_snapshot,
                )
            )

        active_auth_count = sum(
            account.status in _AUTHENTICATED_STATUSES
            for account in workspace_accounts
            if account.email.casefold() != owner_email
        )
        return WorkspaceAuthObservationResponse(
            available=True,
            code="identity_ambiguous" if identity_ambiguous else "ok",
            workspace_id=workspace_id,
            workspace_account_id=workspace_account_id,
            catalog_fingerprint=fingerprint,
            observed_at=observed_at,
            refresh_available=True,
            active_auth_count=active_auth_count,
            identity_ambiguous=identity_ambiguous,
            members=members,
        )

    async def prepare(self, request: MemberAuthHandoffPrepareRequest) -> MemberAuthHandoffResponse:
        async with self._store.lock:
            existing = next(
                (
                    operation
                    for operation in self._store.operations.values()
                    if operation.request.member_switch_operation_id == request.member_switch_operation_id
                ),
                None,
            )
            if existing is not None:
                if existing.request == request:
                    return self._response(existing)
                return self._failure_response(request, "operation_id_conflict")

            active = next(
                (
                    operation
                    for operation in self._store.operations.values()
                    if operation.state not in {"completed", "failed"}
                ),
                None,
            )
            if active is not None:
                return self._failure_response(request, "global_flow_busy")

            handoff = _Handoff(
                handoff_id=str(uuid5(NAMESPACE_URL, "codex-lb/handoff/" + request.member_switch_operation_id)),
                request=request,
                state="prepared",
            )
            if request.membership_state != "active":
                return self._fail_and_store(handoff, "invalid_membership_state")
            if self._identities_overlap(request):
                return self._fail_and_store(handoff, "overlapping_auth_identity")
            catalog = self._catalog_snapshot()
            if request.catalog_fingerprint != catalog.fingerprint():
                return self._fail_and_store(handoff, "catalog_mismatch")
            target_mapping = catalog.find_target(
                preset_id=request.preset_id,
                email=request.target_email,
                user_id=request.target_user_id,
            )
            if target_mapping is None or not self._removed_identity_is_allowlisted(
                request,
                target_mapping.workspace_id,
                catalog,
            ):
                return self._fail_and_store(handoff, "handoff_identity_not_allowlisted")
            if request.workspace_account_id != target_mapping.workspace_account_id:
                return self._fail_and_store(handoff, "workspace_account_unmapped")
            existing_target = next(
                (
                    operation
                    for operation in self._store.operations.values()
                    if operation.state
                    in {
                        "device_code_issued",
                        "browser_opened",
                        "user_action_required",
                        "oauth_pending",
                        "oauth_verified",
                    }
                    and operation.request.workspace_account_id == request.workspace_account_id
                    and operation.request.target_email.casefold() == request.target_email.casefold()
                    and operation.request.target_user_id == request.target_user_id
                    and operation.request.catalog_fingerprint == request.catalog_fingerprint
                ),
                None,
            )
            if existing_target is not None:
                return self._response(existing_target)

            accounts = await self._repository.list_accounts(refresh_existing=True)
            workspace_accounts = [
                account for account in accounts if account.chatgpt_account_id == request.workspace_account_id
            ]
            if any(
                (
                    request.removed_email is not None
                    and account.email.casefold() == request.removed_email.casefold()
                    and account.chatgpt_user_id == request.target_user_id
                )
                or (
                    request.removed_user_id is not None
                    and account.chatgpt_user_id == request.removed_user_id
                    and account.email.casefold() == request.target_email.casefold()
                )
                for account in workspace_accounts
            ):
                return self._fail_and_store(handoff, "overlapping_auth_identity")
            old_matches = self._old_auth_candidates(
                workspace_accounts,
                request,
                target_mapping.workspace_id,
                catalog,
            )
            target_matches = self._matching_accounts(
                accounts,
                request.workspace_account_id,
                request.target_email,
                request.target_user_id,
            )
            old_partial = self._partial_identity_matches(
                workspace_accounts,
                request.removed_email,
                request.removed_user_id,
                old_matches,
            )
            target_partial = self._partial_identity_matches(
                workspace_accounts,
                request.target_email,
                request.target_user_id,
                target_matches,
            )
            if old_partial:
                return self._fail_and_store(handoff, "ambiguous_old_auth")
            if target_partial:
                return self._fail_and_store(handoff, "ambiguous_target_auth")
            if len(old_matches) > 1:
                return self._fail_and_store(handoff, "ambiguous_old_auth")
            if len(target_matches) > 1:
                return self._fail_and_store(handoff, "ambiguous_target_auth")

            old_account = old_matches[0] if old_matches else None
            target_account = target_matches[0] if target_matches else None
            if request.preserve_other_auth and target_account is not None:
                if target_account.status in _AUTHENTICATED_STATUSES:
                    return self._fail_and_store(handoff, "target_auth_already_active")
                if (
                    target_account.status == AccountStatus.PAUSED
                    and target_account.deactivation_reason == _QUARANTINE_REASON
                ):
                    return self._fail_and_store(handoff, "target_auth_quarantine_mismatch")
            handoff.intended_account_id = target_account.id if target_account else None
            if self._local_accounts_overlap(old_account, target_account, request):
                return self._fail_and_store(handoff, "overlapping_auth_identity")
            if old_account is not None:
                handoff.removed_auth_usage_snapshot = await self._capture_removed_auth_usage(old_account.id)
                handoff.old_account_id = old_account.id
                handoff.old_account_email = old_account.email.casefold()
                handoff.old_account_user_id = old_account.chatgpt_user_id
                await self._checkpoint(handoff)
                if old_account.status == AccountStatus.PAUSED:
                    if old_account.deactivation_reason != _QUARANTINE_REASON:
                        return self._fail_and_store(handoff, "old_auth_quarantine_mismatch")
                elif old_account.status in _AUTHENTICATED_STATUSES:
                    updated = await self._repository.update_status(
                        old_account.id,
                        AccountStatus.PAUSED,
                        _QUARANTINE_REASON,
                        blocked_at=None,
                    )
                    if not updated:
                        return self._fail_and_store(handoff, "old_auth_quarantine_failed")
                else:
                    return self._fail_and_store(handoff, "old_auth_quarantine_mismatch")
                handoff.state = "old_auth_quarantined"
                await self._checkpoint(handoff)
                mark_account_routing_unavailable(old_account.id)
                get_account_selection_cache().invalidate()
                get_api_key_cache().clear()
                await propagate_account_routing_change()

            await self._checkpoint(handoff)
            oauth_error = await self._issue_device_code(handoff)
            if oauth_error is not None:
                return self._fail_and_store(handoff, oauth_error)
            self._store.operations[handoff.handoff_id] = handoff
            await self._checkpoint(handoff)
            return self._response(handoff)

    async def _capture_removed_auth_usage(self, account_id: str) -> MemberAuthUsageSnapshot | None:
        if self._usage is None:
            return None
        try:
            usage = await self._latest_long_usage(account_id)
        except Exception:
            return MemberAuthUsageSnapshot()
        if usage is None:
            return MemberAuthUsageSnapshot()
        return MemberAuthUsageSnapshot(
            remaining_percent=usage_core.remaining_percent_from_used(usage.used_percent),
            reset_at=self._reset_datetime(usage),
            observed_at=self._observed_datetime(usage),
        )

    async def list_catalog_member_usage(self) -> CatalogMemberUsageResponse:
        accounts = await self._repository.list_accounts(refresh_existing=True)
        members: list[CatalogMemberUsage] = []
        for entry in self._catalog_snapshot().entries:
            matches = [
                account
                for account in accounts
                if account.chatgpt_account_id == entry.workspace_account_id
                and account.email.casefold() == entry.email.casefold()
                and account.chatgpt_user_id == entry.user_id
                and account.status in _AUTHENTICATED_STATUSES
            ]
            if len(matches) > 1:
                members.append(
                    CatalogMemberUsage(
                        workspace_id=entry.workspace_id,
                        preset_id=entry.preset_id,
                        workspace_account_id=entry.workspace_account_id,
                        email=entry.email,
                        user_id=entry.user_id,
                        availability="ambiguous_auth",
                    )
                )
                continue
            if not matches:
                members.append(
                    CatalogMemberUsage(
                        workspace_id=entry.workspace_id,
                        preset_id=entry.preset_id,
                        workspace_account_id=entry.workspace_account_id,
                        email=entry.email,
                        user_id=entry.user_id,
                        availability="auth_unavailable",
                    )
                )
                continue

            account = matches[0]
            try:
                usage = await self._latest_long_usage(account.id)
            except Exception:
                usage = None
            if usage is None:
                if account.status == AccountStatus.QUOTA_EXCEEDED and account.blocked_at is not None:
                    members.append(
                        CatalogMemberUsage(
                            workspace_id=entry.workspace_id,
                            preset_id=entry.preset_id,
                            workspace_account_id=entry.workspace_account_id,
                            email=entry.email,
                            user_id=entry.user_id,
                            auth_account_id=account.id,
                            auth_status=account.status.value,
                            availability="available",
                            remaining_percent=0,
                            reset_at=(
                                datetime.fromtimestamp(float(account.reset_at), tz=timezone.utc)
                                if account.reset_at is not None
                                else None
                            ),
                            observed_at=datetime.fromtimestamp(
                                float(account.blocked_at),
                                tz=timezone.utc,
                            ),
                        )
                    )
                    continue
                members.append(
                    CatalogMemberUsage(
                        workspace_id=entry.workspace_id,
                        preset_id=entry.preset_id,
                        workspace_account_id=entry.workspace_account_id,
                        email=entry.email,
                        user_id=entry.user_id,
                        auth_account_id=account.id,
                        auth_status=account.status.value,
                        availability="usage_unavailable",
                    )
                )
                continue
            members.append(
                CatalogMemberUsage(
                    workspace_id=entry.workspace_id,
                    preset_id=entry.preset_id,
                    workspace_account_id=entry.workspace_account_id,
                    email=entry.email,
                    user_id=entry.user_id,
                    auth_account_id=account.id,
                    auth_status=account.status.value,
                    availability="available",
                    remaining_percent=usage_core.remaining_percent_from_used(usage.used_percent),
                    reset_at=self._reset_datetime(usage),
                    observed_at=self._observed_datetime(usage),
                )
            )
        return CatalogMemberUsageResponse(members=members)

    async def _latest_long_usage(self, account_id: str) -> UsageHistory | None:
        if self._usage is None:
            return None
        usage = await self._usage.latest_entry_for_account(account_id, window="monthly")
        if usage is not None:
            return usage
        usage = await self._usage.latest_entry_for_account(account_id, window="secondary")
        if usage is not None:
            return usage
        primary_usage = await self._usage.latest_entry_for_account(account_id, window="primary")
        if primary_usage is not None and (
            usage_core.is_weekly_window_minutes(primary_usage.window_minutes)
            or usage_core.is_monthly_window_minutes(primary_usage.window_minutes)
            or primary_usage.window_minutes == _OPENAI_AVERAGE_MONTH_WINDOW_MINUTES
        ):
            return primary_usage
        return None

    @staticmethod
    def _reset_datetime(usage: UsageHistory) -> datetime | None:
        if usage.reset_at is None:
            return None
        return datetime.fromtimestamp(usage.reset_at, tz=timezone.utc)

    @staticmethod
    def _observed_datetime(usage: UsageHistory) -> datetime:
        observed_at = usage.recorded_at
        if observed_at.tzinfo is None:
            return observed_at.replace(tzinfo=timezone.utc)
        return observed_at.astimezone(timezone.utc)

    async def get_status(self, handoff_id: str) -> MemberAuthHandoffResponse | None:
        """Read the last stored observation without advancing OAuth or routing."""
        async with self._store.lock:
            handoff = self._store.operations.get(handoff_id)
            return None if handoff is None else self._response(handoff)

    async def advance(self, handoff_id: str) -> MemberAuthHandoffResponse | None:
        async with self._store.lock:
            handoff = self._store.operations.get(handoff_id)
            if handoff is None:
                return None
            if handoff.state in {"completed", "failed"} or handoff.flow_id is None:
                return self._response(handoff)

            status = await self._oauth.oauth_status(handoff.flow_id)
            if status.status == "pending":
                handoff.state = "oauth_pending"
            elif status.status == "success":
                handoff.state = "oauth_verified"
                try:
                    accounts = await self._repository.list_accounts(refresh_existing=True)
                except Exception:
                    handoff.error_code = "observation_unavailable"
                    return self._response(handoff)
                target_matches = self._matching_accounts(
                    accounts,
                    handoff.request.workspace_account_id,
                    handoff.request.target_email,
                    handoff.request.target_user_id,
                )
                workspace_accounts = [
                    account
                    for account in accounts
                    if account.chatgpt_account_id == handoff.request.workspace_account_id
                ]
                if len(target_matches) > 1 or self._partial_identity_matches(
                    workspace_accounts,
                    handoff.request.target_email,
                    handoff.request.target_user_id,
                    target_matches,
                ):
                    return self._fail_and_store(handoff, "ambiguous_target_auth")
                if not target_matches or target_matches[0].status not in _AUTHENTICATED_STATUSES:
                    handoff.error_code = "target_auth_not_observed"
                    return self._response(handoff)
                handoff.error_code = None

                if handoff.old_auth_deleted:
                    old_matches = []
                elif handoff.old_account_id is not None:
                    retained_old_accounts = [account for account in accounts if account.id == handoff.old_account_id]
                    if retained_old_accounts and any(
                        account.chatgpt_account_id != handoff.request.workspace_account_id
                        or account.email.casefold() != handoff.old_account_email
                        or account.chatgpt_user_id != handoff.old_account_user_id
                        for account in retained_old_accounts
                    ):
                        return self._fail_and_store(handoff, "old_auth_identity_mismatch")
                    old_matches = retained_old_accounts
                else:
                    old_matches = self._matching_accounts(
                        accounts,
                        handoff.request.workspace_account_id,
                        handoff.request.removed_email,
                        handoff.request.removed_user_id,
                    )
                if len(old_matches) > 1:
                    return self._fail_and_store(handoff, "ambiguous_old_auth")
                if old_matches:
                    old_account = old_matches[0]
                    if (
                        old_account.status != AccountStatus.PAUSED
                        or old_account.deactivation_reason != _QUARANTINE_REASON
                    ):
                        return self._fail_and_store(handoff, "old_auth_quarantine_mismatch")
                    await self._checkpoint(handoff)
                    if not await self._repository.delete(old_account.id):
                        return self._fail_and_store(handoff, "old_auth_delete_failed")
                    handoff.state = "old_auth_deleted"
                    handoff.old_auth_deleted = True
                    await self._checkpoint(handoff)
                    get_account_selection_cache().invalidate()
                    get_api_key_cache().clear()
                    await propagate_account_routing_change()
                handoff.state = "completed"
            elif status.status == "error":
                if status.error_message == _DEVICE_CODE_EXPIRED_MESSAGE:
                    if handoff.request.preserve_other_auth:
                        handoff.state = "failed"
                        handoff.error_code = "device_code_expired_requires_new_enrollment"
                        handoff.error_message = status.error_message
                        return self._response(handoff)
                    if handoff.device_code_reissues >= _MAX_DEVICE_CODE_REISSUES:
                        handoff.state = "failed"
                        handoff.error_code = "device_code_reissue_exhausted"
                        handoff.error_message = status.error_message
                    else:
                        handoff.device_code_reissues += 1
                        await self._checkpoint(handoff)
                        if await self._issue_device_code(handoff) is not None:
                            handoff.state = "failed"
                            handoff.error_code = "device_code_reissue_failed"
                            handoff.error_message = "A fresh device code could not be issued."
                else:
                    handoff.state = "failed"
                    handoff.error_code = "oauth_identity_or_authorization_failed"
                    handoff.error_message = status.error_message
            return self._response(handoff)

    async def _issue_device_code(self, handoff: _Handoff) -> str | None:
        request = handoff.request
        try:
            oauth = await self._oauth.start_oauth(
                OauthStartRequest(
                    force_method="device",
                    account_id=handoff.intended_account_id,
                    expected_email=request.target_email,
                    expected_chatgpt_user_id=request.target_user_id,
                    expected_chatgpt_account_id=request.workspace_account_id,
                )
            )
        except Exception:
            return "oauth_start_failed"
        if not oauth.flow_id or not oauth.verification_url or not oauth.user_code:
            return "oauth_start_invalid"

        handoff.flow_id = oauth.flow_id
        handoff.verification_url = oauth.verification_url
        handoff.user_code = oauth.user_code
        handoff.expires_in_seconds = oauth.expires_in_seconds
        handoff.error_code = None
        handoff.error_message = None
        handoff.state = "device_code_issued"
        return None

    @staticmethod
    def _matching_accounts(
        accounts: list[Account],
        workspace_account_id: str,
        email: str | None,
        user_id: str | None,
    ) -> list[Account]:
        if email is None or user_id is None:
            return []
        normalized_email = email.casefold()
        return [
            account
            for account in accounts
            if account.chatgpt_account_id == workspace_account_id
            and account.email.casefold() == normalized_email
            and account.chatgpt_user_id == user_id
        ]

    @staticmethod
    def _old_auth_candidates(
        workspace_accounts: list[Account],
        request: MemberAuthHandoffPrepareRequest,
        workspace_id: str,
        catalog: MemberAuthHandoffCatalog,
    ) -> list[Account]:
        if request.preserve_other_auth:
            return []
        if request.removed_email is not None and request.removed_user_id is not None:
            return MemberAuthHandoffService._matching_accounts(
                workspace_accounts,
                request.workspace_account_id,
                request.removed_email,
                request.removed_user_id,
            )

        target_email = request.target_email.casefold()
        return [
            account
            for account in workspace_accounts
            if not (account.email.casefold() == target_email and account.chatgpt_user_id == request.target_user_id)
            and catalog.contains_member(
                workspace_id=workspace_id,
                email=account.email,
                user_id=account.chatgpt_user_id,
            )
            and (
                account.status in _AUTHENTICATED_STATUSES
                or (account.status == AccountStatus.PAUSED and account.deactivation_reason == _QUARANTINE_REASON)
            )
        ]

    @staticmethod
    def _partial_identity_matches(
        accounts: list[Account],
        email: str | None,
        user_id: str | None,
        exact_matches: list[Account],
    ) -> list[Account]:
        if email is None or user_id is None:
            return []
        normalized_email = email.casefold()
        exact_ids = {account.id for account in exact_matches}
        return [
            account
            for account in accounts
            if account.id not in exact_ids
            and (account.email.casefold() == normalized_email or account.chatgpt_user_id == user_id)
        ]

    @staticmethod
    def _identities_overlap(request: MemberAuthHandoffPrepareRequest) -> bool:
        return (
            request.removed_email is not None and request.removed_email.casefold() == request.target_email.casefold()
        ) or request.removed_user_id == request.target_user_id

    def _removed_identity_is_allowlisted(
        self,
        request: MemberAuthHandoffPrepareRequest,
        workspace_id: str,
        catalog: MemberAuthHandoffCatalog,
    ) -> bool:
        if request.removed_email is None or request.removed_user_id is None:
            return True
        return catalog.contains_member(
            workspace_id=workspace_id,
            email=request.removed_email,
            user_id=request.removed_user_id,
        )

    @staticmethod
    def _local_accounts_overlap(
        old_account: Account | None,
        target_account: Account | None,
        request: MemberAuthHandoffPrepareRequest,
    ) -> bool:
        if old_account is not None and old_account.chatgpt_user_id == request.target_user_id:
            return True
        if target_account is not None and target_account.chatgpt_user_id == request.removed_user_id:
            return True
        return old_account is not None and target_account is not None and old_account.id == target_account.id

    def _fail_and_store(self, handoff: _Handoff, code: str) -> MemberAuthHandoffResponse:
        handoff.state = "failed"
        handoff.error_code = code
        self._store.operations[handoff.handoff_id] = handoff
        return self._response(handoff)

    @classmethod
    def _failure_response(
        cls,
        request: MemberAuthHandoffPrepareRequest,
        code: str,
    ) -> MemberAuthHandoffResponse:
        return cls._response(
            _Handoff(
                handoff_id=secrets.token_urlsafe(18),
                request=request,
                state="failed",
                error_code=code,
            )
        )

    @staticmethod
    def _response(handoff: _Handoff) -> MemberAuthHandoffResponse:
        request = handoff.request
        return MemberAuthHandoffResponse(
            handoff_id=handoff.handoff_id,
            member_switch_operation_id=request.member_switch_operation_id,
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            removed_email=request.removed_email,
            removed_auth_usage_snapshot=handoff.removed_auth_usage_snapshot,
            state=handoff.state,
            flow_id=handoff.flow_id,
            verification_url=handoff.verification_url,
            user_code=handoff.user_code,
            expires_in_seconds=handoff.expires_in_seconds,
            error_code=handoff.error_code,
            error_message=handoff.error_message,
        )
