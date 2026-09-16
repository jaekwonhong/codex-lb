from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.core.clients.usage import UsageFetchError
from app.core.crypto import TokenEncryptor
from app.core.usage.models import RateLimitPayload, UsagePayload, UsageWindow
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, UsageHistory
from app.modules.usage import updater as updater_module
from app.modules.usage.updater import UsageRepositoryPort, UsageUpdater, usage_account_identity

pytestmark = [pytest.mark.unit, pytest.mark.usage_refresh_request_path]


@pytest.fixture(autouse=True)
def isolated_refresh(monkeypatch: pytest.MonkeyPatch):
    updater_module._clear_usage_refresh_state()
    monkeypatch.setattr(updater_module, "_resolve_upstream_route_for_account", AsyncMock(return_value=None))
    # Legacy event production is outside P1 and must not touch the local catalog/store.
    monkeypatch.setattr(updater_module, "observe_successful_usage", AsyncMock(return_value=False))
    yield
    updater_module._clear_usage_refresh_state()


@pytest.fixture
def account() -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id="local-seat-a",
        chatgpt_account_id="upstream-workspace-a",
        chatgpt_user_id="user-a",
        email="member@example.com",
        workspace_id="metadata-workspace-a",
        plan_type="business",
        access_token_encrypted=encryptor.encrypt("synthetic-access-token"),
        refresh_token_encrypted=encryptor.encrypt("synthetic-refresh-token"),
        id_token_encrypted=encryptor.encrypt("synthetic-id-token"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
    )


def _payload(*, weekly: bool = True, primary_only: bool = False, used: float = 100) -> UsagePayload:
    window = UsageWindow(
        used_percent=used,
        limit_window_seconds=604800 if weekly else 18000,
        reset_at=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    )
    return UsagePayload(
        workspace_id="metadata-workspace-a",
        plan_type="business",
        rate_limit=RateLimitPayload(
            primary_window=window if primary_only else None,
            secondary_window=None if primary_only else window,
        ),
    )


def _repo(account: Account) -> AsyncMock:
    repo = AsyncMock(spec=UsageRepositoryPort)
    repo.add_account_snapshot.return_value = []
    repo.latest_entry_for_account.return_value = UsageHistory(
        account_id=account.id,
        window="secondary",
        used_percent=100,
        window_minutes=10080,
        reset_at=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        recorded_at=utcnow() - timedelta(days=1),
    )
    return repo


@pytest.mark.parametrize("written", [False, True])
async def test_successful_fetch_has_fresh_evidence_independent_of_written_row(account, monkeypatch, written) -> None:
    payload = _payload(primary_only=True)
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    repo = _repo(account)
    if written:
        repo.add_account_snapshot.return_value = [repo.latest_entry_for_account.return_value]
    before = datetime.now(timezone.utc)
    observation = await UsageUpdater(repo).force_weekly_observation(account)
    assert observation.fetch_succeeded is True and observation.usage_written is written
    assert observation.provenance is not None
    assert observation.provenance.started_at >= before
    assert observation.provenance.observed_at >= observation.provenance.started_at
    assert observation.window is not None and observation.window.source_slot == "primary"
    assert observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state == "exhausted"
    assert repo.add_account_snapshot.call_args.args[1][0].window == "primary"
    assert fetch.call_args.kwargs["account_id"] == account.chatgpt_account_id
    cast(AsyncMock, updater_module.observe_successful_usage).assert_not_called()
    # The observation is a snapshot, not a reference to the mutable parsed payload.
    assert payload.rate_limit is not None
    assert payload.rate_limit.primary_window is not None
    payload.rate_limit.primary_window.used_percent = 0
    assert observation.window.raw_used_percent == 100


async def test_rotation_receipt_captures_five_hour_and_weekly_from_one_fetch(account, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    payload = UsagePayload(
        workspace_id="metadata-workspace-a",
        plan_type="business",
        rate_limit=RateLimitPayload(
            primary_window=UsageWindow(
                used_percent=12.5,
                limit_window_seconds=18000,
                reset_at=int((now + timedelta(hours=1)).timestamp()),
            ),
            secondary_window=UsageWindow(
                used_percent=100,
                limit_window_seconds=604800,
                reset_at=int((now + timedelta(days=1)).timestamp()),
            ),
        ),
    )
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    receipt = await UsageUpdater(_repo(account)).force_rotation_usage_observation(account)

    assert fetch.await_count == 1
    assert receipt.fetch_succeeded is True
    assert receipt.provenance is not None
    assert receipt.five_hour_window is not None
    assert receipt.five_hour_window.source_slot == "primary"
    assert receipt.five_hour_window.raw_used_percent == 12.5
    assert receipt.weekly_window is not None
    assert receipt.weekly_window.source_slot == "secondary"
    assert receipt.weekly_window.raw_used_percent == 100
    assert (
        receipt.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state
        == "exhausted"
    )


async def test_failed_fetch_does_not_borrow_old_weekly_row(account, monkeypatch) -> None:
    monkeypatch.setattr(updater_module, "fetch_usage", AsyncMock(side_effect=UsageFetchError(503, "Synthetic failure")))
    repo = _repo(account)
    result = await UsageUpdater(repo).force_refresh_result(account)
    assert result.fetch_succeeded is False and result.usage_written is False
    assert result.five_hour_window is None and result.weekly_window is None and result.fetch_provenance is None
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state
        == "unknown"
    )
    repo.add_account_snapshot.assert_not_called()
    assert repo.latest_entry_for_account.return_value.used_percent == 100


async def test_fresh_five_hour_fetch_does_not_refresh_stored_weekly(account, monkeypatch) -> None:
    monkeypatch.setattr(
        updater_module, "fetch_usage", AsyncMock(return_value=_payload(weekly=False, primary_only=True))
    )
    repo = _repo(account)
    result = await UsageUpdater(repo).force_refresh_result(account)
    assert result.fetch_succeeded is True
    assert result.fetch_provenance is not None
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).reason
        == "weekly_missing"
    )
    assert repo.add_account_snapshot.call_args.args[1][0].window_minutes == 300
    assert repo.latest_entry_for_account.return_value.window_minutes == 10080


async def test_payload_workspace_mismatch_has_no_weekly_evidence(account, monkeypatch) -> None:
    payload = _payload()
    payload.workspace_id = "wrong-workspace"
    monkeypatch.setattr(updater_module, "fetch_usage", AsyncMock(return_value=payload))
    repo = _repo(account)
    result = await UsageUpdater(repo).force_refresh_result(account)
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state
        == "unknown"
    )
    repo.add_account_snapshot.assert_not_called()


async def test_fetch_binds_identity_before_in_place_member_change(account, monkeypatch) -> None:
    old_identity = usage_account_identity(account)

    async def fetch(**kwargs) -> UsagePayload:
        account.chatgpt_user_id = "user-b"
        account.email = "replacement@example.com"
        return _payload()

    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    result = await UsageUpdater(_repo(account)).force_refresh_result(account)
    assert result.fetch_provenance is not None and result.fetch_provenance.identity == old_identity
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).reason
        == "identity_mismatch"
    )


async def test_override_token_is_not_attributed_to_stored_member(account, monkeypatch) -> None:
    monkeypatch.setattr(updater_module, "fetch_usage", AsyncMock(return_value=_payload()))
    result = await UsageUpdater(_repo(account)).force_refresh_result(
        account, access_token_override="synthetic-other-token"
    )
    assert result.fetch_succeeded is True
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).reason
        == "unverified_credentials"
    )


async def test_separate_successful_unchanged_fetches_have_distinct_provenance(account, monkeypatch) -> None:
    fetch = AsyncMock(return_value=_payload())
    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    updater = UsageUpdater(_repo(account))
    first = await updater.force_refresh_result(account)
    second = await updater.force_refresh_result(account)
    assert first.fetch_provenance is not None and second.fetch_provenance is not None
    assert first.fetch_provenance.fetch_id != second.fetch_provenance.fetch_id
    assert second.fetch_provenance.started_at >= first.fetch_provenance.observed_at
    assert first.usage_written is False and second.usage_written is False
    assert fetch.await_count == 2


async def test_freshness_skip_does_not_claim_a_successful_fetch(account, monkeypatch) -> None:
    fetch = AsyncMock(return_value=_payload())
    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    repo = _repo(account)
    repo.latest_entry_for_account.return_value.recorded_at = utcnow()
    result = await UsageUpdater(repo)._refresh_account_if_stale(
        account, usage_account_id=account.chatgpt_account_id, interval_seconds=60
    )
    assert result.fetch_succeeded is False and result.fetch_provenance is None
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state
        == "unknown"
    )
    fetch.assert_not_called()


async def test_weekly_entrypoint_bypasses_legacy_confirmation_fetch_and_events(account, monkeypatch) -> None:
    fetch = AsyncMock(side_effect=[_payload(), _payload(used=0)])
    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    legacy = AsyncMock(return_value=True)
    monkeypatch.setattr(updater_module, "observe_successful_usage", legacy)
    updater = UsageUpdater(_repo(account))
    confirmation = AsyncMock()
    monkeypatch.setattr(updater, "_confirm_zero_usage", confirmation)
    observation = await updater.force_weekly_observation(account)
    assert observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state == "exhausted"
    assert fetch.await_count == 1
    legacy.assert_not_called()
    confirmation.assert_not_called()


async def test_legacy_confirmation_does_not_publish_the_earlier_receipt(account, monkeypatch) -> None:
    monkeypatch.setattr(updater_module, "fetch_usage", AsyncMock(return_value=_payload()))
    legacy = AsyncMock(return_value=True)
    monkeypatch.setattr(updater_module, "observe_successful_usage", legacy)
    updater = UsageUpdater(_repo(account))
    confirmation = AsyncMock()
    monkeypatch.setattr(updater, "_confirm_zero_usage", confirmation)
    result = await updater.force_refresh_result(account)
    assert result.fetch_succeeded is True
    assert (
        result.weekly_observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).reason
        == "fetch_not_observed"
    )
    legacy.assert_awaited_once()
    confirmation.assert_awaited_once()


async def test_401_retry_binds_refreshed_credential_and_workspace_header(account, monkeypatch) -> None:
    from app.modules.accounts.auth_manager import AccountsRepositoryPort

    initial_identity = usage_account_identity(account)
    repo = _repo(account)
    accounts_repo = AsyncMock(spec=AccountsRepositoryPort)
    accounts_repo.get_by_id_fresh.return_value = account
    updater = UsageUpdater(repo, accounts_repo=accounts_repo)
    assert updater._auth_manager is not None

    async def refresh(refreshed_account: Account, *, force: bool) -> Account:
        refreshed_account.chatgpt_account_id = "refreshed-workspace"
        refreshed_account.chatgpt_user_id = "refreshed-user"
        return refreshed_account

    monkeypatch.setattr(updater._auth_manager, "ensure_fresh", refresh)
    fetch = AsyncMock(side_effect=[UsageFetchError(401, "Synthetic expiry"), _payload()])
    monkeypatch.setattr(updater_module, "fetch_usage", fetch)
    observation = await updater.force_weekly_observation(account)
    assert fetch.await_args_list[0].kwargs["account_id"] == initial_identity.workspace_account_id
    assert fetch.await_args_list[1].kwargs["account_id"] == "refreshed-workspace"
    assert observation.provenance is not None
    assert observation.provenance.identity == usage_account_identity(account)
    assert observation.assess(initial_identity, now=datetime.now(timezone.utc)).reason == "identity_mismatch"
    assert observation.assess(usage_account_identity(account), now=datetime.now(timezone.utc)).state == "exhausted"
