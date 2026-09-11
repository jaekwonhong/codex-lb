from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.auth.refresh import TokenRefreshResult
from app.core.crypto import TokenEncryptor
from app.db.models import Account, AccountStatus, Base
from app.modules.accounts import auth_manager, background_repository
from app.modules.accounts.auth_manager import AuthManager
from app.modules.accounts.background_repository import BackgroundAccountsRepository

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def background_accounts(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'background.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session_context():
        async with sessions() as session:
            yield session

    monkeypatch.setattr(background_repository, "get_background_session", session_context)
    encryptor = TokenEncryptor()
    account = Account(
        id="background-target",
        email="target@example.com",
        chatgpt_account_id="workspace-synthetic",
        chatgpt_user_id="user-Synthetic",
        plan_type="team",
        status=AccountStatus.ACTIVE,
        routing_policy="normal",
        last_refresh=datetime(2026, 9, 1, tzinfo=timezone.utc),
        access_token_encrypted=encryptor.encrypt("old-access"),
        refresh_token_encrypted=encryptor.encrypt("old-refresh"),
        id_token_encrypted=encryptor.encrypt("old-id"),
    )
    async with sessions() as session:
        session.add(account)
        await session.commit()
    try:
        yield BackgroundAccountsRepository(), account, sessions, encryptor
    finally:
        await engine.dispose()


@pytest.mark.parametrize("enabled,policy", [(True, "normal"), (False, "normal"), (True, "preserve")])
async def test_background_refresh_persists_rotated_tokens_with_workspace_policy(
    background_accounts, monkeypatch, enabled, policy
):
    repo, account, sessions, encryptor = background_accounts
    async with sessions() as session:
        stored = await session.get(Account, account.id)
        stored.routing_policy = policy
        await session.commit()
    account.routing_policy = policy
    manager = AuthManager(repo)
    exchange = AsyncMock(
        return_value=TokenRefreshResult(
            access_token="new-access",
            refresh_token="new-refresh",
            id_token="new-id",
            account_id="workspace-synthetic",
            plan_type="team",
            email="target@example.com",
        )
    )
    monkeypatch.setattr(manager, "_refresh_tokens", exchange)
    monkeypatch.setattr(auth_manager, "fetch_companion_workspace_burn_first", AsyncMock(return_value=enabled))
    monkeypatch.setattr(auth_manager, "propagate_account_routing_change", AsyncMock())
    await manager.refresh_account(account)
    stored = await repo.get_by_id(account.id)
    assert stored is not None
    assert encryptor.decrypt(stored.refresh_token_encrypted) == "new-refresh"
    assert encryptor.decrypt(stored.access_token_encrypted) == "new-access"
    assert stored.routing_policy == ("preserve" if policy == "preserve" else "burn_first" if enabled else "normal")
    exchange.assert_awaited_once()


async def test_background_policy_write_keeps_refresh_ciphertext_compare_and_set(background_accounts):
    repo, account, _, encryptor = background_accounts
    applied = await repo.rotate_tokens(
        account.id,
        b"new-access",
        b"new-refresh",
        b"new-id",
        datetime.now(timezone.utc),
        expected_refresh_token_encrypted=b"not-the-current-ciphertext",
        routing_policy_override="burn_first",
    )
    assert applied is False
    stored = await repo.get_by_id(account.id)
    assert stored is not None and stored.routing_policy == "normal"
    assert encryptor.decrypt(stored.refresh_token_encrypted) == "old-refresh"
