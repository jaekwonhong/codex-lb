from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

_CHATGPT_USER_ID = re.compile(r"^user-[A-Za-z0-9]+$")


@dataclass(frozen=True, slots=True)
class ImportedAccountIdentity:
    user_id: str
    workspace_label: str | None = None
    burn_first_enabled: bool | None = None


def resolve_companion_account_pool_identity(
    path: Path | None,
    *,
    workspace_account_id: str,
    email: str,
) -> ImportedAccountIdentity | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return resolve_companion_account_pool_payload(
        payload,
        workspace_account_id=workspace_account_id,
        email=email,
    )


async def fetch_companion_account_pool_identity(
    url: str | None,
    *,
    workspace_account_id: str,
    email: str,
) -> ImportedAccountIdentity | None:
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.port is None:
        return None
    headers = {
        "Accept": "application/json",
        "Host": f"127.0.0.1:{parsed.port}",
        "Origin": "http://127.0.0.1:2456",
    }
    timeout = aiohttp.ClientTimeout(total=2.0, connect=1.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None
    return resolve_companion_account_pool_payload(
        payload,
        workspace_account_id=workspace_account_id,
        email=email,
    )


def resolve_companion_account_pool_payload(
    payload: object,
    *,
    workspace_account_id: str,
    email: str,
) -> ImportedAccountIdentity | None:
    if not isinstance(payload, dict):
        return None
    accounts = payload.get("Accounts", payload.get("accounts"))
    groups = payload.get("Groups", payload.get("groups"))
    if not isinstance(accounts, list) or not isinstance(groups, list):
        return None

    matching_groups = [
        group
        for group in groups
        if isinstance(group, dict)
        and _field(group, "WorkspaceAccountId", "workspaceAccountId") == workspace_account_id
        and _field(group, "Archived", "archived") is not True
    ]
    normalized_email = email.strip().casefold()
    matching_accounts = [
        account
        for account in accounts
        if isinstance(account, dict)
        and isinstance(_field(account, "Email", "email"), str)
        and _field(account, "Email", "email").strip().casefold() == normalized_email
    ]
    if len(matching_groups) != 1 or len(matching_accounts) != 1:
        return None

    group = matching_groups[0]
    account = matching_accounts[0]
    account_id = _field(account, "Id", "id")
    user_id = _field(account, "UserId", "userId")
    workspace_label = _field(group, "WorkspaceName", "workspaceName")
    burn_first_enabled = _field(group, "BurnFirstEnabled", "burnFirstEnabled")
    assignments = _field(group, "Assignments", "assignments")
    if (
        _field(account, "State", "state") != "ready"
        or not isinstance(account_id, str)
        or not isinstance(user_id, str)
        or _CHATGPT_USER_ID.fullmatch(user_id) is None
        or not isinstance(workspace_label, str)
        or not workspace_label.strip()
        or not isinstance(assignments, list)
    ):
        return None
    matching_assignments = [
        assignment
        for assignment in assignments
        if isinstance(assignment, dict)
        and _field(assignment, "AccountId", "accountId") == account_id
        and _field(assignment, "Included", "included") is True
    ]
    if len(matching_assignments) != 1:
        return None
    return ImportedAccountIdentity(
        user_id=user_id,
        workspace_label=workspace_label.strip(),
        burn_first_enabled=burn_first_enabled if isinstance(burn_first_enabled, bool) else None,
    )


async def fetch_companion_workspace_burn_first(
    url: str | None,
    *,
    workspace_account_id: str,
) -> bool | None:
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.port is None:
        return None
    headers = {
        "Accept": "application/json",
        "Host": f"127.0.0.1:{parsed.port}",
        "Origin": "http://127.0.0.1:2456",
    }
    timeout = aiohttp.ClientTimeout(total=2.0, connect=1.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None
    return resolve_companion_workspace_burn_first_payload(
        payload,
        workspace_account_id=workspace_account_id,
    )


def resolve_companion_workspace_burn_first_payload(
    payload: object,
    *,
    workspace_account_id: str,
) -> bool | None:
    if not isinstance(payload, dict):
        return None
    groups = payload.get("Groups", payload.get("groups"))
    if not isinstance(groups, list):
        return None
    matching_groups = [
        group
        for group in groups
        if isinstance(group, dict)
        and _field(group, "WorkspaceAccountId", "workspaceAccountId") == workspace_account_id
        and _field(group, "Archived", "archived") is not True
    ]
    if len(matching_groups) != 1:
        return None
    enabled = _field(matching_groups[0], "BurnFirstEnabled", "burnFirstEnabled")
    return enabled if isinstance(enabled, bool) else None


def _field(record: dict, file_name: str, api_name: str) -> Any:
    return record.get(file_name, record.get(api_name))


def is_personal_workspace_label(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().casefold() in {
        "personal",
        "personal account",
        "개인 계정",
        "free",
    }
