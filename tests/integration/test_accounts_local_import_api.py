from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.core.auth import generate_unique_account_id
from app.core.config.settings import get_settings

pytestmark = pytest.mark.integration


def _encode_jwt(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{body}.sig"


def _write_auth_json(path: Path, *, account_id: str, email: str) -> None:
    payload: dict[str, object] = {
        "email": email,
        "chatgpt_account_id": account_id,
        "https://api.openai.com/auth": {"chatgpt_plan_type": "team"},
    }
    path.write_text(
        json.dumps(
            {
                "tokens": {
                    "idToken": _encode_jwt(payload),
                    "accessToken": "access-local",
                    "refreshToken": "refresh-local",
                    "accountId": account_id,
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_list_and_import_account_from_configured_local_folder(async_client, monkeypatch, tmp_path: Path) -> None:
    email = "local-import@example.com"
    account_id = "acc_local_import"
    auth_path = tmp_path / "team-auth.json"
    _write_auth_json(auth_path, account_id=account_id, email=email)
    (tmp_path / "ignore.txt").write_text("ignored", encoding="utf-8")
    monkeypatch.setenv("CODEX_LB_OAUTH_IMPORT_DIR", str(tmp_path))
    get_settings.cache_clear()

    listing = await async_client.get("/api/accounts/import/local-files")
    imported = await async_client.post("/api/accounts/import/local", json={"filename": auth_path.name})

    assert listing.status_code == 200
    assert listing.json() == {
        "available": True,
        "files": [{"name": auth_path.name, "sizeBytes": auth_path.stat().st_size}],
    }
    assert imported.status_code == 200
    assert imported.json()["accountId"] == generate_unique_account_id(account_id, email)


@pytest.mark.asyncio
async def test_local_import_api_rejects_traversal(async_client, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_LB_OAUTH_IMPORT_DIR", str(tmp_path))
    get_settings.cache_clear()

    response = await async_client.post("/api/accounts/import/local", json={"filename": "../auth.json"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsafe_oauth_import_filename"
