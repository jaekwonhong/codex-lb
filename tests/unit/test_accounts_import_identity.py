from __future__ import annotations

import json

import pytest
from aiohttp import web

from app.modules.accounts.import_identity import (
    fetch_companion_account_pool_identity,
    resolve_companion_account_pool_identity,
    resolve_companion_workspace_burn_first_payload,
)

pytestmark = pytest.mark.unit


def _write_pool(tmp_path, *, accounts=None, groups=None):
    path = tmp_path / "account-pool.json"
    path.write_text(
        json.dumps(
            {
                "SchemaVersion": 1,
                "Revision": 1,
                "Accounts": accounts
                or [
                    {
                        "Id": "account-member",
                        "Email": "member@example.com",
                        "UserId": "user-Member123",
                        "State": "ready",
                    }
                ],
                "Groups": groups
                or [
                    {
                        "Id": "cdp-1",
                        "WorkspaceName": "workspace-1",
                        "WorkspaceAccountId": "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                        "BurnFirstEnabled": True,
                        "Archived": False,
                        "Assignments": [
                            {"AccountId": "account-member", "Included": True, "Order": 0}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_companion_pool_resolves_one_ready_included_member(tmp_path) -> None:
    resolved = resolve_companion_account_pool_identity(
        _write_pool(tmp_path),
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        email=" MEMBER@EXAMPLE.COM ",
    )

    assert resolved is not None
    assert resolved.user_id == "user-Member123"
    assert resolved.workspace_label == "workspace-1"
    assert resolved.burn_first_enabled is True


def test_companion_pool_resolves_ready_workspace_owner_without_member_assignment(tmp_path) -> None:
    resolved = resolve_companion_account_pool_identity(
        _write_pool(
            tmp_path,
            accounts=[
                {
                    "Id": "account-owner",
                    "Email": "owner@example.com",
                    "UserId": "user-Owner123",
                    "State": "ready",
                }
            ],
            groups=[
                {
                    "Id": "cdp-1",
                    "WorkspaceName": "workspace-1",
                    "WorkspaceAccountId": "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
                    "OwnerAccountId": "account-owner",
                    "BurnFirstEnabled": False,
                    "Archived": False,
                    "Assignments": [],
                }
            ],
        ),
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        email="owner@example.com",
    )

    assert resolved is not None
    assert resolved.user_id == "user-Owner123"
    assert resolved.workspace_label == "workspace-1"
    assert resolved.burn_first_enabled is False


@pytest.mark.asyncio
async def test_companion_pool_http_fetch_uses_beta_origin_and_loopback_host(tmp_path) -> None:
    payload = json.loads(_write_pool(tmp_path).read_text(encoding="utf-8"))
    payload = {
        "revision": payload["Revision"],
        "accounts": [
            {
                "id": item["Id"],
                "email": item["Email"],
                "userId": item["UserId"],
                "state": item["State"],
            }
            for item in payload["Accounts"]
        ],
        "groups": [
            {
                "id": item["Id"],
                "workspaceName": item["WorkspaceName"],
                "workspaceAccountId": item["WorkspaceAccountId"],
                "burnFirstEnabled": item.get("BurnFirstEnabled"),
                "assignments": [
                    {
                        "accountId": assignment["AccountId"],
                        "included": assignment["Included"],
                        "order": assignment["Order"],
                    }
                    for assignment in item["Assignments"]
                ],
            }
            for item in payload["Groups"]
        ],
    }

    async def account_pool(request: web.Request) -> web.Response:
        assert request.headers["Origin"] == "http://127.0.0.1:2456"
        assert request.headers["Host"].startswith("127.0.0.1:")
        return web.json_response(payload)

    app = web.Application()
    app.router.add_get("/member-switch/v1/account-pool", account_pool)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    assert site._server is not None
    port = site._server.sockets[0].getsockname()[1]
    try:
        resolved = await fetch_companion_account_pool_identity(
            f"http://127.0.0.1:{port}/member-switch/v1/account-pool",
            workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
            email="member@example.com",
        )
    finally:
        await runner.cleanup()

    assert resolved is not None
    assert resolved.user_id == "user-Member123"
    assert resolved.workspace_label == "workspace-1"
    assert resolved.burn_first_enabled is True


def test_workspace_burn_first_distinguishes_explicit_off_from_unconfigured() -> None:
    workspace_account_id = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"
    group = {
        "workspaceAccountId": workspace_account_id,
        "burnFirstEnabled": False,
    }

    assert resolve_companion_workspace_burn_first_payload(
        {"groups": [group]},
        workspace_account_id=workspace_account_id,
    ) is False
    assert resolve_companion_workspace_burn_first_payload(
        {"groups": [{"workspaceAccountId": workspace_account_id}]},
        workspace_account_id=workspace_account_id,
    ) is None


@pytest.mark.parametrize("variant", ["excluded", "not_ready", "ambiguous_group", "ambiguous_account"])
def test_companion_pool_fails_closed_for_non_unique_or_ineligible_identity(
    tmp_path,
    variant: str,
) -> None:
    accounts = [
        {
            "Id": "account-member",
            "Email": "member@example.com",
            "UserId": "user-Member123",
            "State": "ready",
        }
    ]
    groups = [
        {
            "Id": "cdp-1",
            "WorkspaceName": "workspace-1",
            "WorkspaceAccountId": "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
            "Archived": False,
            "Assignments": [{"AccountId": "account-member", "Included": True, "Order": 0}],
        }
    ]
    if variant == "excluded":
        groups[0]["Assignments"][0]["Included"] = False
    elif variant == "not_ready":
        accounts[0]["State"] = "login_required"
    elif variant == "ambiguous_group":
        groups.append({**groups[0], "Id": "duplicate"})
    else:
        accounts.append({**accounts[0], "Id": "duplicate"})

    resolved = resolve_companion_account_pool_identity(
        _write_pool(tmp_path, accounts=accounts, groups=groups),
        workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        email="member@example.com",
    )

    assert resolved is None
