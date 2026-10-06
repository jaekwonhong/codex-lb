from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.modules.workspace_member_controller.account_state import OpenCodexAccountState
from app.modules.workspace_member_controller.binding_repository import (
    FileWorkspaceMemberAccountBindingRepository,
)
from app.modules.workspace_member_controller.legacy_canary_runner import (
    CanaryIdentity,
    CanaryState,
    _database_url_from_environment,
    _read_state,
    _require_exact_account,
    _write_state,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)


def _identity(preset: str, user: str) -> CanaryIdentity:
    return CanaryIdentity(
        preset_id=preset,
        email=f"{preset}@example.com",
        user_id=user,
    )


def _state() -> CanaryState:
    return CanaryState(
        schema_version=1,
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        original=_identity("original", "user-Original"),
        target=_identity("target", "user-Target"),
        original_opencodex_account_id="acct-original",
        target_opencodex_account_id="acct-target",
        forward_operation_id="operation-forward",
        forward_completed_at=NOW.isoformat(),
    )


def test_canary_state_file_is_owner_only_and_round_trips(tmp_path: Path):
    path = tmp_path / "canary-state.json"
    expected = _state()

    _write_state(path, expected)

    assert os.stat(path).st_mode & 0o777 == 0o600
    assert _read_state(path) == expected


def test_canary_state_file_rejects_broad_permissions(tmp_path: Path):
    path = tmp_path / "canary-state.json"
    _write_state(path, _state())
    os.chmod(path, 0o644)

    with pytest.raises(RuntimeError, match="canary_state_permissions_too_open"):
        _read_state(path)


def test_canary_database_url_can_be_read_from_owner_only_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "database-url"
    path.write_text("postgresql+asyncpg://example\n", encoding="utf-8")
    os.chmod(path, 0o600)
    monkeypatch.delenv("WMC_CANARY_DATABASE_URL", raising=False)
    monkeypatch.setenv("WMC_CANARY_DATABASE_URL_FILE", str(path))

    assert _database_url_from_environment() == "postgresql+asyncpg://example"


def test_canary_database_url_file_rejects_broad_permissions(tmp_path: Path, monkeypatch):
    path = tmp_path / "database-url"
    path.write_text("postgresql+asyncpg://example\n", encoding="utf-8")
    os.chmod(path, 0o644)
    monkeypatch.delenv("WMC_CANARY_DATABASE_URL", raising=False)
    monkeypatch.setenv("WMC_CANARY_DATABASE_URL_FILE", str(path))

    with pytest.raises(SystemExit, match="database URL file permissions are too open"):
        _database_url_from_environment()


def test_canary_database_url_rejects_ambiguous_inline_and_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "database-url"
    path.write_text("postgresql+asyncpg://example\n", encoding="utf-8")
    os.chmod(path, 0o600)
    monkeypatch.setenv("WMC_CANARY_DATABASE_URL", "postgresql+asyncpg://inline")
    monkeypatch.setenv("WMC_CANARY_DATABASE_URL_FILE", str(path))

    with pytest.raises(SystemExit, match="set only one"):
        _database_url_from_environment()


async def test_exact_opencodex_binding_is_required_before_canary(tmp_path: Path):
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps({"schemaVersion": 1, "bindings": []}) + "\n", encoding="utf-8")
    repository = FileWorkspaceMemberAccountBindingRepository(path)

    class Accounts:
        async def get(self, _account_id):
            raise AssertionError("OpenCodex must not be queried when exact binding is absent")

    with pytest.raises(RuntimeError, match="canary_exact_account_binding_missing:target"):
        await _require_exact_account(
            bindings=repository,
            accounts=Accounts(),  # type: ignore[arg-type]
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            identity=_identity("target", "user-Target"),
        )


def _binding_payload(account_id: str = "acct-target") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "bindings": [
            {
                "schemaVersion": 1,
                "workspaceId": "workspace-1",
                "workspaceAccountId": "workspace-account-1",
                "presetId": "target",
                "memberUserId": "user-Target",
                "memberEmailNormalized": "target@example.com",
                "role": "member",
                "opencodexAccountId": account_id,
                "establishedAt": NOW.isoformat(),
            }
        ],
    }


def _account_state(*, paused: bool, has_credential: bool = True, needs_reauth: bool = False) -> OpenCodexAccountState:
    return OpenCodexAccountState.model_validate(
        {
            "schemaVersion": 1,
            "provider": "openai",
            "accountId": "acct-target",
            "isMain": False,
            "credentialGeneration": 1,
            "observedAt": 1,
            "hasCredential": has_credential,
            "needsReauth": needs_reauth,
            "paused": paused,
            "healthStatus": "healthy",
            "selectionState": "excluded" if paused else "selectable",
            "exclusionReasons": ["paused"] if paused else [],
            "quotaState": "unknown",
            "quotaWindows": [],
            "cooldowns": [],
            "stateRevision": "a" * 64,
        }
    )


async def test_canary_requires_paused_opencodex_account_for_routing_isolation(tmp_path: Path):
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(_binding_payload()) + "\n", encoding="utf-8")
    repository = FileWorkspaceMemberAccountBindingRepository(path)

    class Accounts:
        async def get(self, _account_id):
            return _account_state(paused=False)

    with pytest.raises(RuntimeError, match="canary_opencodex_account_not_isolated:target"):
        await _require_exact_account(
            bindings=repository,
            accounts=Accounts(),  # type: ignore[arg-type]
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            identity=_identity("target", "user-Target"),
        )


async def test_canary_accepts_paused_exact_account_with_usable_credential(tmp_path: Path):
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(_binding_payload()) + "\n", encoding="utf-8")
    repository = FileWorkspaceMemberAccountBindingRepository(path)

    class Accounts:
        async def get(self, _account_id):
            return _account_state(paused=True)

    assert await _require_exact_account(
        bindings=repository,
        accounts=Accounts(),  # type: ignore[arg-type]
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        identity=_identity("target", "user-Target"),
    ) == "acct-target"
