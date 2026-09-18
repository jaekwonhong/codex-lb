from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.db.models import Account, AccountStatus
from app.modules.member_auth_handoff.catalog import (
    PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    MemberAuthCatalogRegistrationError,
    MemberAuthHandoffCatalog,
    MemberAuthHandoffCatalogEntry,
    MemberAuthHandoffCatalogRegistry,
)
from app.modules.member_auth_handoff.repository import MemberAuthCatalogOverlayRepository
from app.modules.member_auth_handoff.schemas import (
    CatalogMemberRegistrationRequest,
    MemberAuthHandoffPrepareRequest,
    MemberAuthReconciliationRequest,
)
from app.modules.member_auth_handoff.service import MemberAuthHandoffService, MemberAuthHandoffStore
from app.modules.oauth.schemas import OauthStartRequest, OauthStartResponse, OauthStatusResponse

pytestmark = pytest.mark.unit


def account(local_id: str, email: str, workspace_account_id: str, status: AccountStatus) -> Account:
    user_id = {
        "allnz.jk@gmail.com": "user-F35N1VBxC5M3BC4LQHhamB8a",
        "thinklet09@gmail.com": "user-9c3ymeVJZPUGcGW9iqJdXhyK",
    }.get(email.casefold(), f"user-{local_id}")
    return Account(
        id=local_id,
        email=email,
        chatgpt_account_id=workspace_account_id,
        chatgpt_user_id=user_id,
        plan_type="team",
        access_token_encrypted="access",
        refresh_token_encrypted="refresh",
        id_token_encrypted="id",
        status=status,
    )


class FakeRepository:
    def __init__(self, accounts: list[Account]) -> None:
        self.accounts = [
            *accounts,
            account(
                "owner-local",
                "jaekwonhong14@gmail.com",
                "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                AccountStatus.ACTIVE,
            ),
        ]
        self.list_calls = 0
        self.status_updates: list[tuple[str, AccountStatus, str | None]] = []
        self.deleted: list[str] = []

    async def list_accounts(self, *, refresh_existing: bool = False) -> list[Account]:
        self.list_calls += 1
        return list(self.accounts)

    async def update_status(
        self,
        account_id: str,
        status: AccountStatus,
        deactivation_reason: str | None = None,
        reset_at: int | None = None,
        blocked_at: int | None | object = ...,
    ) -> bool:
        self.status_updates.append((account_id, status, deactivation_reason))
        current = next((account for account in self.accounts if account.id == account_id), None)
        if current is not None:
            current.status = status
            current.deactivation_reason = deactivation_reason
        return True

    async def update_status_if_current(
        self,
        account_id: str,
        status: AccountStatus,
        deactivation_reason: str | None = None,
        reset_at: int | None = None,
        blocked_at: int | None | object = ...,
        *,
        expected_status: AccountStatus,
        expected_deactivation_reason: str | None = None,
        expected_reset_at: int | None = None,
        expected_blocked_at: int | None | object = ...,
        expected_refresh_token_encrypted: bytes | str | None = None,
    ) -> bool:
        current = next((account for account in self.accounts if account.id == account_id), None)
        if (
            current is None
            or current.status != expected_status
            or current.deactivation_reason != expected_deactivation_reason
            or current.reset_at != expected_reset_at
            or (expected_blocked_at is not ... and current.blocked_at != expected_blocked_at)
            or (
                expected_refresh_token_encrypted is not None
                and current.refresh_token_encrypted != expected_refresh_token_encrypted
            )
        ):
            return False
        return await self.update_status(account_id, status, deactivation_reason, reset_at, blocked_at)

    async def delete(
        self,
        account_id: str,
        *,
        delete_history: bool = False,
        expected_status: AccountStatus | None = None,
        expected_deactivation_reason: str | None = None,
        expected_refresh_token_encrypted: bytes | str | None = None,
    ) -> bool:
        current = next((account for account in self.accounts if account.id == account_id), None)
        if expected_status is not None and (
            current is None
            or current.status != expected_status
            or current.deactivation_reason != expected_deactivation_reason
            or (
                expected_refresh_token_encrypted is not None
                and current.refresh_token_encrypted != expected_refresh_token_encrypted
            )
        ):
            return False
        self.deleted.append(account_id)
        return True


class FailingRefreshRepository(FakeRepository):
    async def list_accounts(self, *, refresh_existing: bool = False) -> list[Account]:
        raise RuntimeError("refresh failed")


class FakeUsageRepository:
    def __init__(self, entries: dict[tuple[str, str], SimpleNamespace] | None = None) -> None:
        self.entries = entries or {}
        self.calls: list[tuple[str, str]] = []

    async def latest_entry_for_account(self, account_id: str, *, window: str | None = None):
        normalized_window = window or "primary"
        self.calls.append((account_id, normalized_window))
        return self.entries.get((account_id, normalized_window))


@dataclass
class FakeOauth:
    status: str = "pending"
    error_message: str | None = None
    device_flow_id: str | None = None

    def __post_init__(self) -> None:
        self.requests: list[OauthStartRequest] = []

    async def start_oauth(self, request: OauthStartRequest) -> OauthStartResponse:
        self.requests.append(request)
        attempt = len(self.requests)
        return OauthStartResponse(
            flow_id=f"flow-{attempt}",
            method="device",
            verification_url="https://auth.openai.com/codex/device",
            user_code=f"ABCD-EFG{attempt}",
            expires_in_seconds=600,
        )

    async def oauth_status(self, flow_id: str | None = None) -> OauthStatusResponse:
        return OauthStatusResponse(status=self.status, error_message=self.error_message)

    async def current_device_flow_id(self) -> str | None:
        return self.device_flow_id


def prepare_request() -> MemberAuthHandoffPrepareRequest:
    return MemberAuthHandoffPrepareRequest(
        member_switch_operation_id="member-operation-1",
        preset_id="cdp-1-thinklet09",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        removed_email="allnz.jk@gmail.com",
        removed_user_id="user-F35N1VBxC5M3BC4LQHhamB8a",
        target_email="thinklet09@gmail.com",
        target_user_id="user-9c3ymeVJZPUGcGW9iqJdXhyK",
        membership_state="active",
        catalog_fingerprint=PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint(),
    )


def test_prepare_request_accepts_active_membership_for_oauth_only_recovery() -> None:
    request = MemberAuthHandoffPrepareRequest.model_validate(
        {
            **prepare_request().model_dump(),
            "removed_email": None,
            "removed_user_id": None,
            "membership_state": "active",
        }
    )

    assert request.membership_state == "active"


def test_prepare_request_rejects_non_active_membership() -> None:
    with pytest.raises(ValidationError):
        MemberAuthHandoffPrepareRequest.model_validate(
            {
                **prepare_request().model_dump(),
                "membership_state": "unknown",
            }
        )


@pytest.mark.asyncio
async def test_prepare_active_membership_starts_oauth_without_old_auth_mutation() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    recovery_request = prepare_request().model_copy(
        update={"membership_state": "active", "removed_email": None, "removed_user_id": None}
    )

    result = await service.prepare(recovery_request)

    assert result.state == "device_code_issued"
    assert repository.status_updates == []
    assert len(oauth.requests) == 1


@pytest.mark.asyncio
async def test_oauth_only_enrollment_preserves_other_managed_auth() -> None:
    old = account(
        "old-local",
        "allnz.jk@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.ACTIVE,
    )
    repository = FakeRepository([old])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    request = prepare_request().model_copy(
        update={
            "removed_email": None,
            "removed_user_id": None,
            "preserve_other_auth": True,
        }
    )

    result = await service.prepare(request)

    assert result.state == "device_code_issued"
    assert result.removed_email is None
    assert repository.status_updates == []
    assert repository.deleted == []
    assert old.status == AccountStatus.ACTIVE
    assert oauth.requests[0].expected_email == request.target_email
    assert oauth.requests[0].expected_chatgpt_user_id == request.target_user_id
    assert oauth.requests[0].expected_chatgpt_account_id == request.workspace_account_id


@pytest.mark.asyncio
async def test_oauth_only_enrollment_does_not_reissue_for_already_active_target() -> None:
    target = account(
        "target-local",
        prepare_request().target_email,
        prepare_request().workspace_account_id,
        AccountStatus.ACTIVE,
    )
    target.chatgpt_user_id = prepare_request().target_user_id
    repository = FakeRepository([target])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    request = prepare_request().model_copy(
        update={
            "removed_email": None,
            "removed_user_id": None,
            "preserve_other_auth": True,
        }
    )

    result = await service.prepare(request)

    assert result.state == "failed"
    assert result.error_code == "target_auth_already_active"
    assert oauth.requests == []
    assert repository.status_updates == []


def test_oauth_only_enrollment_cannot_also_name_removed_auth() -> None:
    with pytest.raises(ValidationError):
        MemberAuthHandoffPrepareRequest.model_validate({**prepare_request().model_dump(), "preserve_other_auth": True})


@pytest.mark.asyncio
async def test_manual_active_member_recovery_infers_and_quarantines_one_old_auth(monkeypatch) -> None:
    repository = FakeRepository(
        [
            account(
                "old-local",
                "allnz.jk@gmail.com",
                prepare_request().workspace_account_id,
                AccountStatus.ACTIVE,
            )
        ]
    )
    oauth = FakeOauth()
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.mark_account_routing_unavailable",
        lambda _id: None,
    )
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.propagate_account_routing_change",
        _noop,
    )
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    recovery_request = prepare_request().model_copy(
        update={"membership_state": "active", "removed_email": None, "removed_user_id": None}
    )

    result = await service.prepare(recovery_request)

    assert result.state == "device_code_issued"
    assert repository.status_updates == [("old-local", AccountStatus.PAUSED, "member_auth_handoff_quarantine")]
    assert len(oauth.requests) == 1


@pytest.mark.asyncio
async def test_manual_active_member_recovery_rejects_multiple_old_auth_candidates() -> None:
    workspace_account_id = prepare_request().workspace_account_id
    second_old = account(
        "second-old-local",
        "thinklet03@gmail.com",
        workspace_account_id,
        AccountStatus.ACTIVE,
    )
    second_old.chatgpt_user_id = "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"
    repository = FakeRepository(
        [
            account(
                "old-local",
                "allnz.jk@gmail.com",
                workspace_account_id,
                AccountStatus.ACTIVE,
            ),
            second_old,
        ]
    )
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    recovery_request = prepare_request().model_copy(
        update={"membership_state": "active", "removed_email": None, "removed_user_id": None}
    )

    result = await service.prepare(recovery_request)

    assert result.state == "failed"
    assert result.error_code == "ambiguous_old_auth"
    assert repository.status_updates == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_rejects_different_workspace_while_handoff_is_nonterminal() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    first = await service.prepare(prepare_request())
    second = await service.prepare(
        MemberAuthHandoffPrepareRequest(
            member_switch_operation_id="member-operation-cdp2",
            preset_id="cdp-2-thinklet09",
            workspace_account_id="85d8ee33-bc27-4413-b3dc-24605885d5b0",
            removed_email=None,
            removed_user_id=None,
            target_email="thinklet09@gmail.com",
            target_user_id="user-9c3ymeVJZPUGcGW9iqJdXhyK",
            membership_state="active",
            catalog_fingerprint=PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint(),
        )
    )

    assert first.state == "device_code_issued"
    assert second.state == "failed"
    assert second.error_code == "global_flow_busy"


@pytest.mark.asyncio
async def test_fresh_recovery_does_not_supersede_a_nonterminal_handoff() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    stale = await service.prepare(prepare_request())
    recovered = await service.prepare(
        prepare_request().model_copy(
            update={
                "member_switch_operation_id": "recovery-fresh-1",
                "removed_email": None,
                "removed_user_id": None,
                "membership_state": "active",
            }
        )
    )

    assert stale.state == "device_code_issued"
    assert recovered.state == "failed"
    assert recovered.error_code == "global_flow_busy"
    assert recovered.handoff_id != stale.handoff_id
    assert len(oauth.requests) == 1
    retained = await service.get_status(stale.handoff_id)
    assert retained is not None
    assert retained.state == "device_code_issued"


@pytest.mark.parametrize(
    "updates",
    [
        {"preset_id": "cdp-2-jaekwonhong14"},
        {"target_email": "thinklet03@gmail.com"},
        {"target_user_id": "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"},
        {"removed_user_id": "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"},
    ],
)
@pytest.mark.asyncio
async def test_prepare_rejects_identity_outside_packaged_catalog_before_lookup(
    updates: dict[str, str],
) -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(prepare_request().model_copy(update=updates))

    assert result.state == "failed"
    assert result.error_code == "handoff_identity_not_allowlisted"
    assert repository.list_calls == 0
    assert repository.status_updates == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_rejects_workspace_id_not_mapped_to_catalog_owner() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(
        prepare_request().model_copy(update={"workspace_account_id": "6411732b-a40b-49fb-8836-2edb52f4a677"})
    )

    assert result.state == "failed"
    assert result.error_code == "workspace_account_unmapped"
    assert repository.list_calls == 0
    assert repository.status_updates == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_uses_cdp2_catalog_mapping_without_owner_auth_row() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    request = MemberAuthHandoffPrepareRequest(
        member_switch_operation_id="member-operation-cdp2",
        preset_id="cdp-2-thinklet09",
        workspace_account_id="85d8ee33-bc27-4413-b3dc-24605885d5b0",
        removed_email="jaekwonhong14@gmail.com",
        removed_user_id="user-pQlg20Jguwdu0SCQgCFxvw6w",
        target_email="thinklet09@gmail.com",
        target_user_id="user-9c3ymeVJZPUGcGW9iqJdXhyK",
        membership_state="active",
        catalog_fingerprint=PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint(),
    )

    result = await service.prepare(request)

    assert result.state == "device_code_issued"
    assert repository.list_calls == 1
    assert oauth.requests[0].expected_chatgpt_account_id == request.workspace_account_id


@pytest.mark.asyncio
async def test_prepare_accepts_oauth_only_owner_entry_without_changing_member_catalog_fingerprint() -> None:
    repository = FakeRepository([])
    # Owner identity authority comes from the Companion account pool. This local
    # auth repository intentionally starts without that target credential.
    repository.accounts.clear()
    oauth = FakeOauth()
    catalog = MemberAuthHandoffCatalog(
        entries=PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.entries,
        owner_entries=(
            MemberAuthHandoffCatalogEntry(
                preset_id="owner:cdp-1",
                workspace_id="cdp-1",
                owner_email="jaekwonhong14@gmail.com",
                workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                email="jaekwonhong14@gmail.com",
                user_id="user-pQlg20Jguwdu0SCQgCFxvw6w",
            ),
        ),
    )
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore(), catalog=catalog)
    request = MemberAuthHandoffPrepareRequest(
        member_switch_operation_id="owner-oauth-cdp1",
        preset_id="owner:cdp-1",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        removed_email=None,
        removed_user_id=None,
        target_email="jaekwonhong14@gmail.com",
        target_user_id="user-pQlg20Jguwdu0SCQgCFxvw6w",
        membership_state="active",
        catalog_fingerprint=PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint(),
        preserve_other_auth=True,
    )

    result = await service.prepare(request)

    assert catalog.fingerprint() == PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint()
    assert (
        catalog.find_target(
            preset_id=request.preset_id,
            email=request.target_email,
            user_id=request.target_user_id,
        )
        is None
    )
    assert (
        catalog.find_auth_target(
            preset_id=request.preset_id,
            email=request.target_email,
            user_id=request.target_user_id,
        )
        is not None
    )
    assert result.state == "device_code_issued"
    assert repository.status_updates == []
    assert len(oauth.requests) == 1


def test_packaged_catalog_has_exact_workspace_account_ids() -> None:
    account_ids_by_workspace = {
        entry.workspace_id: entry.workspace_account_id for entry in PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.entries
    }

    assert account_ids_by_workspace == {
        "cdp-1": "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        "cdp-2": "85d8ee33-bc27-4413-b3dc-24605885d5b0",
        "cdp-3": "5b9ab31e-fceb-4661-9655-1f479369c68f",
    }


@pytest.mark.asyncio
async def test_prepare_rejects_operation_id_reuse_with_different_request() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    original = await service.prepare(prepare_request())
    conflicting_request = prepare_request().model_copy(
        update={
            "preset_id": "cdp-1-thinklet03",
            "target_email": "thinklet03@gmail.com",
            "target_user_id": "user-9I446YqZTQ9z0Wq6zCzvJ0Sl",
        }
    )

    conflict = await service.prepare(conflicting_request)

    assert original.state == "device_code_issued"
    assert conflict.state == "failed"
    assert conflict.error_code == "operation_id_conflict"
    assert conflict.handoff_id != original.handoff_id
    assert repository.list_calls == 1
    assert len(oauth.requests) == 1


@pytest.mark.asyncio
async def test_prepare_quarantines_exact_removed_auth_before_device_oauth(monkeypatch):
    events: list[str] = []

    class OrderedRepository(FakeRepository):
        async def update_status(
            self,
            account_id: str,
            status: AccountStatus,
            deactivation_reason: str | None = None,
            reset_at: int | None = None,
            blocked_at: int | None | object = ...,
        ) -> bool:
            events.append("quarantine")
            return await super().update_status(
                account_id,
                status,
                deactivation_reason,
                reset_at,
                blocked_at,
            )

    class OrderedOauth(FakeOauth):
        async def start_oauth(self, request: OauthStartRequest) -> OauthStartResponse:
            events.append("oauth")
            return await super().start_oauth(request)

    repository = OrderedRepository(
        [
            account(
                "old-local",
                "ALLNZ.JK@GMAIL.COM",
                prepare_request().workspace_account_id,
                AccountStatus.ACTIVE,
            )
        ]
    )
    oauth = OrderedOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(prepare_request())

    assert result.state == "device_code_issued"
    assert repository.status_updates == [("old-local", AccountStatus.PAUSED, "member_auth_handoff_quarantine")]
    assert repository.deleted == []
    assert events == ["quarantine", "oauth"]
    oauth_request = oauth.requests[0]
    assert oauth_request.force_method == "device"
    assert oauth_request.expected_email == "thinklet09@gmail.com"
    assert oauth_request.expected_chatgpt_user_id == "user-9c3ymeVJZPUGcGW9iqJdXhyK"
    assert oauth_request.expected_chatgpt_account_id == prepare_request().workspace_account_id


@pytest.mark.asyncio
async def test_prepare_stale_quarantine_cannot_overwrite_newer_reauth_required(monkeypatch) -> None:
    class RacingRepository(FakeRepository):
        async def update_status(
            self,
            account_id: str,
            status: AccountStatus,
            deactivation_reason: str | None = None,
            reset_at: int | None = None,
            blocked_at: int | None | object = ...,
        ) -> bool:
            current = next(item for item in self.accounts if item.id == account_id)
            current.status = AccountStatus.REAUTH_REQUIRED
            current.deactivation_reason = "Refresh token was reused - re-login required"
            return await super().update_status(account_id, status, deactivation_reason, reset_at, blocked_at)

        async def update_status_if_current(self, *args, **kwargs) -> bool:
            account_id = args[0]
            current = next(item for item in self.accounts if item.id == account_id)
            current.status = AccountStatus.REAUTH_REQUIRED
            current.deactivation_reason = "Refresh token was reused - re-login required"
            return await super().update_status_if_current(*args, **kwargs)

    request = prepare_request()
    old = account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)
    repository = RacingRepository([old])
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(request)

    assert result.state == "failed"
    assert result.error_code == "old_auth_quarantine_failed"
    assert old.status == AccountStatus.REAUTH_REQUIRED
    assert old.deactivation_reason == "Refresh token was reused - re-login required"
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_blocks_device_oauth_when_removed_auth_quarantine_fails(monkeypatch) -> None:
    class QuarantineFailingRepository(FakeRepository):
        async def update_status(
            self,
            account_id: str,
            status: AccountStatus,
            deactivation_reason: str | None = None,
            reset_at: int | None = None,
            blocked_at: int | None | object = ...,
        ) -> bool:
            self.status_updates.append((account_id, status, deactivation_reason))
            return False

    request = prepare_request()
    repository = QuarantineFailingRepository(
        [account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)]
    )
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(request)

    assert result.state == "failed"
    assert result.error_code == "old_auth_quarantine_failed"
    assert repository.deleted == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_snapshots_monthly_usage_before_quarantining_removed_auth(monkeypatch):
    request = prepare_request()
    repository = FakeRepository(
        [account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)]
    )
    reset_epoch = 1_785_000_000
    usage = FakeUsageRepository(
        {
            ("old-local", "monthly"): SimpleNamespace(
                used_percent=72.5,
                reset_at=reset_epoch,
                recorded_at=datetime(2026, 7, 24, 3, 4, 5),
            ),
        }
    )
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(
        repository,
        oauth,
        MemberAuthHandoffStore(),
        usage_repository=usage,
    )

    result = await service.prepare(request)

    assert result.removed_email == request.removed_email
    assert result.removed_auth_usage_snapshot is not None
    assert result.removed_auth_usage_snapshot.remaining_percent == 27.5
    assert result.removed_auth_usage_snapshot.reset_at == datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
    assert result.removed_auth_usage_snapshot.observed_at == datetime(2026, 7, 24, 3, 4, 5, tzinfo=timezone.utc)
    assert usage.calls == [("old-local", "monthly")]
    assert repository.status_updates == [("old-local", AccountStatus.PAUSED, "member_auth_handoff_quarantine")]
    assert repository.deleted == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window_minutes", "used_percent", "remaining_percent"),
    [
        (10_080, 4.0, 96.0),
        (43_800, 37.5, 62.5),
    ],
)
async def test_prepare_snapshots_primary_labelled_long_usage_before_quarantine(
    monkeypatch,
    window_minutes,
    used_percent,
    remaining_percent,
):
    request = prepare_request()
    repository = FakeRepository(
        [account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)]
    )
    reset_epoch = 1_785_487_000
    usage = FakeUsageRepository(
        {
            ("old-local", "primary"): SimpleNamespace(
                used_percent=used_percent,
                reset_at=reset_epoch,
                window_minutes=window_minutes,
                recorded_at=datetime(2026, 7, 24, 3, 5, tzinfo=timezone.utc),
            ),
        }
    )
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(
        repository,
        oauth,
        MemberAuthHandoffStore(),
        usage_repository=usage,
    )

    result = await service.prepare(request)

    assert result.removed_auth_usage_snapshot is not None
    assert result.removed_auth_usage_snapshot.remaining_percent == remaining_percent
    assert result.removed_auth_usage_snapshot.reset_at == datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
    assert usage.calls == [
        ("old-local", "monthly"),
        ("old-local", "secondary"),
        ("old-local", "primary"),
    ]


@pytest.mark.asyncio
async def test_list_catalog_member_usage_returns_typed_distinct_observation() -> None:
    member = account(
        "member-local",
        "allnz.jk@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.QUOTA_EXCEEDED,
    )
    member.chatgpt_user_id = "user-F35N1VBxC5M3BC4LQHhamB8a"
    usage = FakeUsageRepository(
        {
            ("member-local", "secondary"): SimpleNamespace(
                used_percent=100.0,
                reset_at=1_785_487_000,
                recorded_at=datetime(2026, 7, 24, 4, 5, 6, tzinfo=timezone.utc),
            )
        }
    )
    service = MemberAuthHandoffService(
        FakeRepository([member]),
        FakeOauth(),
        MemberAuthHandoffStore(),
        usage_repository=usage,
    )

    result = await service.list_catalog_member_usage()

    selected = next(item for item in result.members if item.preset_id == "cdp-1-allnz-jk")
    assert selected.availability == "available"
    assert selected.auth_account_id == "member-local"
    assert selected.auth_status == "quota_exceeded"
    assert selected.remaining_percent == 0
    assert selected.observed_at == datetime(2026, 7, 24, 4, 5, 6, tzinfo=timezone.utc)
    assert usage.calls == [
        ("member-local", "monthly"),
        ("member-local", "secondary"),
    ]


@pytest.mark.asyncio
async def test_list_catalog_member_usage_projects_fresh_quota_status_without_usage_history() -> None:
    member = account(
        "member-local",
        "allnz.jk@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.QUOTA_EXCEEDED,
    )
    member.chatgpt_user_id = "user-F35N1VBxC5M3BC4LQHhamB8a"
    member.blocked_at = 1_775_353_506
    member.reset_at = 1_775_440_000
    service = MemberAuthHandoffService(
        FakeRepository([member]),
        FakeOauth(),
        MemberAuthHandoffStore(),
        usage_repository=FakeUsageRepository(),
    )

    result = await service.list_catalog_member_usage()

    selected = next(item for item in result.members if item.preset_id == "cdp-1-allnz-jk")
    assert selected.availability == "available"
    assert selected.auth_account_id == "member-local"
    assert selected.auth_status == "quota_exceeded"
    assert selected.remaining_percent == 0
    assert selected.observed_at == datetime.fromtimestamp(1_775_353_506, tz=timezone.utc)
    assert selected.reset_at == datetime.fromtimestamp(1_775_440_000, tz=timezone.utc)


@pytest.mark.asyncio
async def test_list_catalog_member_usage_distinguishes_missing_auth_usage_and_ambiguity() -> None:
    no_usage = account(
        "no-usage",
        "thinklet03@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.ACTIVE,
    )
    no_usage.chatgpt_user_id = "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"
    duplicate_a = account(
        "duplicate-a",
        "thinklet09@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.ACTIVE,
    )
    duplicate_b = account(
        "duplicate-b",
        "thinklet09@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.RATE_LIMITED,
    )
    duplicate_a.chatgpt_user_id = duplicate_b.chatgpt_user_id = "user-9c3ymeVJZPUGcGW9iqJdXhyK"
    service = MemberAuthHandoffService(
        FakeRepository([no_usage, duplicate_a, duplicate_b]),
        FakeOauth(),
        MemberAuthHandoffStore(),
        usage_repository=FakeUsageRepository(),
    )

    result = await service.list_catalog_member_usage()

    by_preset = {item.preset_id: item for item in result.members}
    assert by_preset["cdp-1-allnz-jk"].availability == "auth_unavailable"
    assert by_preset["cdp-1-thinklet03"].availability == "usage_unavailable"
    assert by_preset["cdp-1-thinklet03"].auth_account_id == "no-usage"
    assert by_preset["cdp-1-thinklet09"].availability == "ambiguous_auth"


@pytest.mark.asyncio
async def test_prepare_without_prior_auth_returns_no_snapshot_and_does_not_query_usage() -> None:
    repository = FakeRepository([])
    usage = FakeUsageRepository()
    service = MemberAuthHandoffService(
        repository,
        FakeOauth(),
        MemberAuthHandoffStore(),
        usage_repository=usage,
    )

    result = await service.prepare(prepare_request())

    assert result.state == "device_code_issued"
    assert result.removed_email == prepare_request().removed_email
    assert result.removed_auth_usage_snapshot is None
    assert usage.calls == []


@pytest.mark.asyncio
async def test_prepare_rejects_ambiguous_prior_auth_before_mutation():
    request = prepare_request()
    repository = FakeRepository(
        [
            account("old-a", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE),
            account("old-b", request.removed_email or "", request.workspace_account_id, AccountStatus.REAUTH_REQUIRED),
        ]
    )
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(request)

    assert result.state == "failed"
    assert result.error_code == "ambiguous_old_auth"
    assert repository.status_updates == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_rejects_overlapping_removed_and_target_auth_before_mutation():
    request = prepare_request().model_copy(
        update={
            "removed_email": prepare_request().target_email,
            "removed_user_id": prepare_request().target_user_id,
        }
    )
    repository = FakeRepository(
        [account("same-local", request.target_email, request.workspace_account_id, AccountStatus.ACTIVE)]
    )
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(request)

    assert result.state == "failed"
    assert result.error_code == "overlapping_auth_identity"
    assert repository.status_updates == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_prepare_rejects_prior_local_row_with_target_user_identity() -> None:
    request = prepare_request()
    prior = account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)
    prior.chatgpt_user_id = request.target_user_id
    repository = FakeRepository([prior])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    result = await service.prepare(request)

    assert result.state == "failed"
    assert result.error_code == "overlapping_auth_identity"
    assert repository.status_updates == []
    assert oauth.requests == []


@pytest.mark.asyncio
async def test_removed_auth_is_deleted_only_after_verified_oauth_success(monkeypatch):
    request = prepare_request()
    repository = FakeRepository(
        [account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)]
    )
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    prepared = await service.prepare(request)

    pending = await service.advance(prepared.handoff_id)
    assert pending is not None and pending.state == "oauth_pending"
    assert repository.deleted == []

    oauth.status = "success"
    repository.accounts.append(
        account(
            "target-local",
            request.target_email,
            request.workspace_account_id,
            AccountStatus.ACTIVE,
        )
    )
    completed = await service.advance(prepared.handoff_id)
    assert completed is not None and completed.state == "completed"
    assert repository.deleted == ["old-local"]
    await service.advance(prepared.handoff_id)
    assert repository.deleted == ["old-local"]


@pytest.mark.asyncio
async def test_oauth_success_stale_cleanup_cannot_delete_concurrently_reauthenticated_old_row(monkeypatch) -> None:
    request = prepare_request()

    class DeleteRaceRepository(FakeRepository):
        async def delete(self, account_id: str, **kwargs) -> bool:
            current = next(item for item in self.accounts if item.id == account_id)
            current.status = AccountStatus.ACTIVE
            current.deactivation_reason = None
            current.refresh_token_encrypted = "peer-reauth-refresh"
            return await super().delete(account_id, **kwargs)

    old = account("old-local", request.removed_email or "", request.workspace_account_id, AccountStatus.ACTIVE)
    repository = DeleteRaceRepository([old])
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    prepared = await service.prepare(request)
    assert prepared.state == "device_code_issued"

    oauth.status = "success"
    repository.accounts.append(
        account("target-local", request.target_email, request.workspace_account_id, AccountStatus.ACTIVE)
    )
    completed = await service.advance(prepared.handoff_id)

    assert completed is not None
    assert completed.state == "failed"
    assert completed.error_code == "old_auth_delete_failed"
    assert old.status == AccountStatus.ACTIVE
    assert old.refresh_token_encrypted == "peer-reauth-refresh"
    assert repository.deleted == []


@pytest.mark.asyncio
async def test_status_deletes_inferred_quarantined_auth_after_oauth_success(monkeypatch) -> None:
    request = prepare_request().model_copy(update={"removed_email": None, "removed_user_id": None})
    repository = FakeRepository(
        [
            account(
                "old-local",
                "allnz.jk@gmail.com",
                request.workspace_account_id,
                AccountStatus.ACTIVE,
            )
        ]
    )
    oauth = FakeOauth()
    monkeypatch.setattr("app.modules.member_auth_handoff.service.mark_account_routing_unavailable", lambda _id: None)
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    prepared = await service.prepare(request)

    oauth.status = "success"
    repository.accounts.append(
        account(
            "target-local",
            request.target_email,
            request.workspace_account_id,
            AccountStatus.ACTIVE,
        )
    )
    completed = await service.advance(prepared.handoff_id)

    assert completed is not None and completed.state == "completed"
    assert repository.deleted == ["old-local"]


@pytest.mark.asyncio
async def test_reconcile_cleanup_deletes_one_exact_old_quarantined_auth(monkeypatch) -> None:
    request = prepare_request()
    target = account(
        "target-local",
        request.target_email,
        request.workspace_account_id,
        AccountStatus.ACTIVE,
    )
    old = account(
        "old-local",
        request.removed_email or "",
        request.workspace_account_id,
        AccountStatus.PAUSED,
    )
    old.deactivation_reason = "member_auth_handoff_quarantine"
    repository = FakeRepository([target, old])
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    result = await service.reconcile_auth(
        MemberAuthReconciliationRequest(
            action="cleanup_old_auth",
            workspace_id="cdp-1",
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            membership_state="active",
            catalog_fingerprint=request.catalog_fingerprint,
        )
    )

    assert result.accepted is True
    assert result.code == "old_auth_deleted"
    assert repository.deleted == ["old-local"]


@pytest.mark.asyncio
async def test_reconcile_unpause_reactivates_only_exact_handoff_quarantined_target(monkeypatch) -> None:
    request = prepare_request()
    target = account(
        "target-local",
        request.target_email,
        request.workspace_account_id,
        AccountStatus.PAUSED,
    )
    target.deactivation_reason = "member_auth_handoff_quarantine"
    repository = FakeRepository([target])
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    result = await service.reconcile_auth(
        MemberAuthReconciliationRequest(
            action="unpause_target_auth",
            workspace_id="cdp-1",
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            membership_state="active",
            catalog_fingerprint=request.catalog_fingerprint,
        )
    )

    assert result.accepted is True
    assert result.code == "target_auth_unpaused"
    assert repository.status_updates == [("target-local", AccountStatus.ACTIVE, None)]


@pytest.mark.asyncio
async def test_reconcile_unpause_stale_snapshot_cannot_revive_reauth_required_target(monkeypatch) -> None:
    request = prepare_request()

    class RacingRepository(FakeRepository):
        async def update_status(
            self,
            account_id: str,
            status: AccountStatus,
            deactivation_reason: str | None = None,
            reset_at: int | None = None,
            blocked_at: int | None | object = ...,
        ) -> bool:
            current = next(item for item in self.accounts if item.id == account_id)
            current.status = AccountStatus.REAUTH_REQUIRED
            current.deactivation_reason = "Refresh token was reused - re-login required"
            return await super().update_status(account_id, status, deactivation_reason, reset_at, blocked_at)

        async def update_status_if_current(self, *args, **kwargs) -> bool:
            account_id = args[0]
            current = next(item for item in self.accounts if item.id == account_id)
            current.status = AccountStatus.REAUTH_REQUIRED
            current.deactivation_reason = "Refresh token was reused - re-login required"
            return await super().update_status_if_current(*args, **kwargs)

    target = account("target-local", request.target_email, request.workspace_account_id, AccountStatus.PAUSED)
    target.deactivation_reason = "member_auth_handoff_quarantine"
    repository = RacingRepository([target])
    monkeypatch.setattr(
        "app.modules.member_auth_handoff.service.get_account_selection_cache",
        lambda: type("Cache", (), {"invalidate": lambda self: None})(),
    )
    monkeypatch.setattr("app.modules.member_auth_handoff.service.propagate_account_routing_change", _noop)
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    result = await service.reconcile_auth(
        MemberAuthReconciliationRequest(
            action="unpause_target_auth",
            workspace_id="cdp-1",
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            membership_state="active",
            catalog_fingerprint=request.catalog_fingerprint,
        )
    )

    assert result.accepted is False
    assert result.code == "target_auth_unpause_failed"
    assert target.status == AccountStatus.REAUTH_REQUIRED
    assert target.deactivation_reason == "Refresh token was reused - re-login required"


@pytest.mark.asyncio
async def test_reconcile_cleanup_is_idempotent_when_old_auth_is_absent() -> None:
    request = prepare_request()
    repository = FakeRepository(
        [
            account(
                "target-local",
                request.target_email,
                request.workspace_account_id,
                AccountStatus.ACTIVE,
            )
        ]
    )
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    result = await service.reconcile_auth(
        MemberAuthReconciliationRequest(
            action="cleanup_old_auth",
            workspace_id="cdp-1",
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            membership_state="active",
            catalog_fingerprint=request.catalog_fingerprint,
        )
    )

    assert result.accepted is True
    assert result.code == "already_clean"
    assert repository.deleted == []


@pytest.mark.asyncio
async def test_reconcile_unpause_preserves_unrelated_pause_reason() -> None:
    request = prepare_request()
    target = account(
        "target-local",
        request.target_email,
        request.workspace_account_id,
        AccountStatus.PAUSED,
    )
    target.deactivation_reason = "operator_pause"
    repository = FakeRepository([target])
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    result = await service.reconcile_auth(
        MemberAuthReconciliationRequest(
            action="unpause_target_auth",
            workspace_id="cdp-1",
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            membership_state="active",
            catalog_fingerprint=request.catalog_fingerprint,
        )
    )

    assert result.accepted is False
    assert result.code == "target_auth_quarantine_mismatch"
    assert repository.status_updates == []


@pytest.mark.asyncio
async def test_status_reissues_one_expired_device_code_without_replaying_membership() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth(status="error", error_message="Device code expired.")
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    prepared = await service.prepare(prepare_request())

    refreshed = await service.advance(prepared.handoff_id)

    assert refreshed is not None
    assert refreshed.state == "device_code_issued"
    assert refreshed.flow_id == "flow-2"
    assert refreshed.user_code == "ABCD-EFG2"
    assert refreshed.error_code is None
    assert len(oauth.requests) == 2
    assert repository.list_calls == 1
    assert repository.status_updates == []
    assert repository.deleted == []

    exhausted = await service.advance(prepared.handoff_id)

    assert exhausted is not None
    assert exhausted.state == "failed"
    assert exhausted.error_code == "device_code_reissue_exhausted"
    assert len(oauth.requests) == 2
    assert repository.deleted == []


@pytest.mark.asyncio
async def test_oauth_only_expiry_never_auto_reissues_device_code() -> None:
    repository = FakeRepository([])
    oauth = FakeOauth(status="error", error_message="Device code expired.")
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    request = prepare_request().model_copy(
        update={
            "removed_email": None,
            "removed_user_id": None,
            "preserve_other_auth": True,
        }
    )
    prepared = await service.prepare(request)

    expired = await service.advance(prepared.handoff_id)

    assert expired is not None
    assert expired.state == "failed"
    assert expired.error_code == "device_code_expired_requires_new_enrollment"
    assert expired.flow_id == "flow-1"
    assert len(oauth.requests) == 1
    assert repository.status_updates == []
    assert repository.deleted == []


async def _noop() -> None:
    return None


def candidate_request(**updates: str) -> CatalogMemberRegistrationRequest:
    values = {
        "workspace_id": "cdp-1",
        "preset_id": "custom-cdp-1-new-member",
        "display_name": "new.member",
        "email": "new.member@gmail.com",
        "user_id": "user-NewMember123",
    }
    values.update(updates)
    return CatalogMemberRegistrationRequest(**values)


def test_catalog_registration_rejects_auth_account_uuid_as_user_id() -> None:
    with pytest.raises(ValidationError):
        candidate_request(user_id="bd19f6be-2447-4bb3-a9cd-cc68813347f0")


def test_catalog_registration_uses_companion_display_name_limit() -> None:
    candidate_request(display_name="a" * 80)

    with pytest.raises(ValidationError):
        candidate_request(display_name="a" * 81)


def test_catalog_registration_persists_and_reloads_effective_candidate(tmp_path) -> None:
    path = tmp_path / "member-auth-handoff-catalog.json"
    registry = MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(path),
        PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    )

    created = registry.register(candidate_request())
    idempotent = registry.register(candidate_request())
    reloaded = MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(path),
        PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    ).effective_catalog()

    assert created.accepted is True
    assert created.code == "created"
    assert idempotent.code == "already_registered"
    assert (
        reloaded.find_target(
            preset_id="custom-cdp-1-new-member",
            email="NEW.MEMBER@gmail.com",
            user_id="user-NewMember123",
        )
        is not None
    )


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"email": "jaekwonhong14@gmail.com"}, "owner_not_allowed"),
        ({"email": "allnz.jk@gmail.com"}, "email_conflict"),
        ({"user_id": "user-F35N1VBxC5M3BC4LQHhamB8a"}, "user_id_conflict"),
        ({"workspace_id": "cdp-missing"}, "workspace_not_found"),
    ],
)
def test_catalog_registration_rejects_invalid_workspace_identity(
    tmp_path,
    updates: dict[str, str],
    code: str,
) -> None:
    registry = MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(tmp_path / "catalog.json"),
        PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    )

    with pytest.raises(MemberAuthCatalogRegistrationError) as exc_info:
        registry.register(candidate_request(**updates))

    assert exc_info.value.code == code


def test_catalog_registration_enforces_companion_workspace_capacity(tmp_path) -> None:
    registry = MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(tmp_path / "catalog.json"),
        PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    )
    for index in range(15):
        registry.register(
            candidate_request(
                preset_id=f"custom-cdp-1-candidate-{index}",
                display_name=f"candidate-{index}",
                email=f"candidate-{index}@example.com",
                user_id=f"user-Candidate{index}",
            )
        )

    with pytest.raises(MemberAuthCatalogRegistrationError) as exc_info:
        registry.register(
            candidate_request(
                preset_id="custom-cdp-1-over-capacity",
                display_name="over-capacity",
                email="over-capacity@example.com",
                user_id="user-OverCapacity",
            )
        )

    assert exc_info.value.code == "workspace_capacity_exceeded"


@pytest.mark.asyncio
async def test_handoff_and_usage_use_persisted_custom_candidate(tmp_path) -> None:
    registry = MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(tmp_path / "catalog.json"),
        PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    )
    registry.register(candidate_request())
    repository = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(
        repository,
        oauth,
        MemberAuthHandoffStore(),
        usage_repository=FakeUsageRepository(),
        catalog_registry=registry,
    )
    request = MemberAuthHandoffPrepareRequest(
        member_switch_operation_id="custom-operation",
        preset_id="custom-cdp-1-new-member",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        removed_email="allnz.jk@gmail.com",
        removed_user_id="user-F35N1VBxC5M3BC4LQHhamB8a",
        target_email="new.member@gmail.com",
        target_user_id="user-NewMember123",
        membership_state="active",
        catalog_fingerprint=registry.effective_catalog().fingerprint(),
    )

    prepared = await service.prepare(request)
    usage = await service.list_catalog_member_usage()

    assert prepared.state == "device_code_issued"
    assert oauth.requests[0].expected_chatgpt_user_id == "user-NewMember123"
    custom_usage = next(member for member in usage.members if member.preset_id == "custom-cdp-1-new-member")
    assert custom_usage.availability == "auth_unavailable"


def test_catalog_fingerprint_is_canonical_across_entry_order_and_email_case() -> None:
    reversed_catalog = MemberAuthHandoffCatalog(
        entries=tuple(
            replace(entry, email=entry.email.upper())
            for entry in reversed(PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.entries)
        )
    )

    assert reversed_catalog.fingerprint() == PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint()


@pytest.mark.asyncio
async def test_workspace_auth_observation_reports_refresh_failure_as_unavailable() -> None:
    service = MemberAuthHandoffService(
        FailingRefreshRepository([]),
        FakeOauth(),
        MemberAuthHandoffStore(),
    )

    observation = await service.observe_workspace_auth(
        workspace_id="cdp-1",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
    )

    assert observation.available is False
    assert observation.refresh_available is False
    assert observation.code == "observation_unavailable"
    assert observation.members == []


@pytest.mark.asyncio
async def test_workspace_auth_observation_keeps_auth_presence_separate_from_usage() -> None:
    repository = FakeRepository(
        [
            account(
                "target-local",
                "thinklet09@gmail.com",
                "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                AccountStatus.ACTIVE,
            )
        ]
    )
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    observation = await service.observe_workspace_auth(
        workspace_id="cdp-1",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
    )

    target = next(member for member in observation.members if member.preset_id == "cdp-1-thinklet09")
    assert observation.available is True
    assert observation.identity_ambiguous is False
    assert observation.active_auth_count == 1
    assert target.state == "active"
    assert target.usage is None


@pytest.mark.asyncio
async def test_workspace_auth_observation_allows_multiple_exact_managed_auths() -> None:
    workspace_account_id = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"
    first = account("first-local", "allnz.jk@gmail.com", workspace_account_id, AccountStatus.ACTIVE)
    second = account("second-local", "thinklet09@gmail.com", workspace_account_id, AccountStatus.ACTIVE)
    service = MemberAuthHandoffService(
        FakeRepository([first, second]),
        FakeOauth(),
        MemberAuthHandoffStore(),
    )

    observation = await service.observe_workspace_auth(
        workspace_id="cdp-1",
        workspace_account_id=workspace_account_id,
    )

    assert observation.active_auth_count == 2
    assert observation.identity_ambiguous is False
    assert observation.code == "ok"
    active_members = [member for member in observation.members if member.state == "active"]
    assert len(active_members) == 2
    assert {member.email for member in active_members} == {"allnz.jk@gmail.com", "thinklet09@gmail.com"}


@pytest.mark.asyncio
async def test_workspace_auth_observation_fails_closed_on_partial_identity_collision() -> None:
    collision = account(
        "collision-local",
        "thinklet09@gmail.com",
        "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        AccountStatus.ACTIVE,
    )
    collision.chatgpt_user_id = "user-Different123"
    service = MemberAuthHandoffService(
        FakeRepository([collision]),
        FakeOauth(),
        MemberAuthHandoffStore(),
    )

    observation = await service.observe_workspace_auth(
        workspace_id="cdp-1",
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
    )

    target = next(member for member in observation.members if member.preset_id == "cdp-1-thinklet09")
    assert observation.identity_ambiguous is True
    assert observation.code == "identity_ambiguous"
    assert target.state == "ambiguous"


@pytest.mark.asyncio
async def test_prepare_rejects_catalog_mismatch_before_auth_mutation() -> None:
    repository = FakeRepository(
        [
            account(
                "old-local",
                "allnz.jk@gmail.com",
                "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                AccountStatus.ACTIVE,
            )
        ]
    )
    service = MemberAuthHandoffService(repository, FakeOauth(), MemberAuthHandoffStore())

    result = await service.prepare(prepare_request().model_copy(update={"catalog_fingerprint": "b" * 64}))

    assert result.state == "failed"
    assert result.error_code == "catalog_mismatch"
    assert repository.status_updates == []


@pytest.mark.asyncio
async def test_prepare_rejects_same_target_with_a_different_operation_id() -> None:
    repository = FakeRepository(
        [
            account(
                "old-local",
                "allnz.jk@gmail.com",
                "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                AccountStatus.ACTIVE,
            )
        ]
    )
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())

    first = await service.prepare(prepare_request())
    second = await service.prepare(
        prepare_request().model_copy(update={"member_switch_operation_id": "member-operation-2"})
    )

    assert second.handoff_id != first.handoff_id
    assert second.state == "failed"
    assert second.error_code == "global_flow_busy"
    assert len(oauth.requests) == 1
    assert repository.status_updates == [("old-local", AccountStatus.PAUSED, "member_auth_handoff_quarantine")]
    assert repository.deleted == []


@pytest.mark.asyncio
async def test_oauth_success_without_target_auth_keeps_old_auth_quarantined() -> None:
    request = prepare_request()
    repository = FakeRepository(
        [
            account(
                "old-local",
                request.removed_email or "",
                request.workspace_account_id,
                AccountStatus.ACTIVE,
            )
        ]
    )
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repository, oauth, MemberAuthHandoffStore())
    prepared = await service.prepare(request)

    oauth.status = "success"
    result = await service.advance(prepared.handoff_id)

    assert result is not None
    assert result.state == "oauth_verified"
    assert result.error_code == "target_auth_not_observed"
    assert repository.deleted == []
    assert repository.status_updates == [("old-local", AccountStatus.PAUSED, "member_auth_handoff_quarantine")]


@pytest.mark.parametrize(
    "oauth_state,error_message", [("pending", None), ("success", None), ("error", "Device code expired.")]
)
async def test_status_is_a_stored_snapshot_without_side_effects(oauth_state, error_message):
    from unittest.mock import AsyncMock

    repo = FakeRepository([])
    oauth = FakeOauth()
    service = MemberAuthHandoffService(repo, oauth, store=MemberAuthHandoffStore())
    request = prepare_request().model_copy(update={"removed_email": None, "removed_user_id": None})
    prepared = await service.prepare(request)
    oauth.status, oauth.error_message = oauth_state, error_message
    oauth.oauth_status = AsyncMock(side_effect=AssertionError("GET must not contact OAuth"))
    repo.list_accounts = AsyncMock(side_effect=AssertionError("GET must not inspect accounts"))
    repo.delete = AsyncMock(side_effect=AssertionError("GET must not delete auth"))
    before_requests = len(oauth.requests)
    for _ in range(3):
        assert await service.get_status(prepared.handoff_id) == prepared
    assert await service.get_status("missing") is None
    assert len(oauth.requests) == before_requests
    oauth.oauth_status.assert_not_called()
    repo.list_accounts.assert_not_called()
    repo.delete.assert_not_called()
