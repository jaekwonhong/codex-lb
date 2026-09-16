"""ASGI -> production dependencies -> database/HTTP adapters -> synthetic peers.

Companion examples are emitted by its actual services and source-generated JSON
serializer under fake drivers. No network listener, browser or OAuth server is used.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.dependencies as dependencies
from app.core.auth.dashboard_access import Permission
from app.core.auth.dependencies import require_dashboard_permission, validate_dashboard_session
from app.db.models import Account, AccountStatus, Base
from app.db.session import get_session
from app.modules.member_auth_handoff.api import router as auth_router
from app.modules.member_auth_handoff.catalog import MemberAuthHandoffCatalog, MemberAuthHandoffCatalogEntry
from app.modules.member_switch.api import handle_control_conflict, router
from app.modules.member_switch.participants import participant_fingerprint
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.schemas import ParticipantRequest
from app.modules.oauth.schemas import OauthStartResponse, OauthStatusResponse

pytestmark = pytest.mark.integration
ROOT = "/api/member-switch-runs"


class SyntheticWire:
    """Intercept ClientSession at the transport seam, not the typed Companion port."""

    def __init__(self, examples):
        self.examples = examples
        self.participant_receipts = {}
        self.calls = []
        self.unavailable_page = False
        self.unknown_browser_outcome = False
        self.lose = None
        self.started = False
        self.finalized = False
        self.release_pending = False
        self.interrupt_finalize_once = False
        self.reject_start = False
        self.wait_start = None
        self.start_entered = asyncio.Event()

    def session(self, **options):
        assert options["trust_env"] is False
        owner = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def request(self, method, url, **kwargs):
                assert kwargs["allow_redirects"] is False
                assert kwargs["headers"]["X-Member-Switch-Protocol"] == "managed_member_switch_v1"
                assert kwargs["headers"]["Host"] == "127.0.0.1:53418"
                assert kwargs["headers"]["Origin"] == "http://127.0.0.1:2456"
                path = urlsplit(url).path.removeprefix("/member-switch/v1")
                owner.calls.append((method, path, kwargs.get("json")))
                return owner.response(method, path, kwargs.get("json"))

        return Session()

    def response(self, method, path, body):
        examples = self.examples
        operation_id = examples["operation"]["operationId"]
        status = 200
        if method == "GET" and path == "/catalog":
            payload = examples["catalog"]
        elif method == "GET" and path == "/admission":
            payload = examples["admission"]
        elif method == "POST" and path == "/previews":
            workspace = examples["catalog"]["workspaces"][0]
            assert body == {
                "workspaceAccountId": workspace["workspaceAccountId"],
                "presetId": workspace["members"][0]["presetId"],
                "catalogFingerprint": examples["catalog"]["catalogFingerprint"],
            }
            payload = copy.deepcopy(examples["preview"])
            payload["expiresAt"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        elif method == "POST" and path == "/operations":
            assert body["previewToken"] == examples["preview"]["previewToken"]
            self.started = not self.reject_start
            payload = (
                examples["start"]
                if self.started
                else {"accepted": False, "operationId": None, "code": "preview_expired"}
            )
        elif method == "GET" and path.startswith("/client-flows/"):
            status = 200 if self.started else 404
            if self.finalized:
                payload = examples["lookupFinalized"]
            elif self.release_pending:
                payload = copy.deepcopy(examples["start"])
                payload["code"] = "operation_release_pending"
            else:
                payload = examples["start"]
        elif method == "GET" and path == "/operations/" + operation_id:
            assert self.started
            payload = examples["operation"]
        elif method == "POST" and path == "/participant-commands":
            request = ParticipantRequest.model_validate(body)
            assert request.member_switch_operation_id == operation_id
            action = request.action
            key = {"prepare_session": "session", "open_browser": "browser", "close_browser": "close"}[action]
            result = (
                examples["readiness"]
                if action == "prepare_session"
                else examples["closed"]
                if action == "close_browser"
                else examples[
                    "browserUnknown"
                    if self.unknown_browser_outcome
                    else "browserUnavailable"
                    if self.unavailable_page
                    else "browser"
                ]
            )
            payload = {
                "schemaVersion": 1,
                "commandId": request.command_id,
                "clientFlowId": request.client_flow_id,
                "action": action,
                "memberSwitchOperationId": operation_id,
                "identity": body["identity"],
                "requestHash": participant_fingerprint(request),
                "browserOperationId": request.browser_operation_id,
                "state": "pending" if result.get("outcomeUnknown") else "completed",
                "code": result["code"],
                "recordedAt": datetime.now(timezone.utc).isoformat(),
            }
            if payload["state"] == "completed":
                payload[key] = result
            self.participant_receipts[request.command_id] = copy.deepcopy(payload)
        elif method == "POST" and path.startswith("/participant-commands/") and path.endswith("/reconcile"):
            command_id = path.removeprefix("/participant-commands/").removesuffix("/reconcile")
            payload = self.participant_receipts.get(command_id)
            status = 404 if payload is None else 200
        elif method == "GET" and path.startswith("/participant-commands/"):
            payload = self.participant_receipts.get(path.rsplit("/", 1)[-1])
            status = 404 if payload is None else 200
        elif method == "POST" and path == f"/operations/{operation_id}/finalize":
            if self.interrupt_finalize_once:
                self.interrupt_finalize_once = False
                self.release_pending = True
            else:
                self.finalized = True
                self.release_pending = False
            payload = examples["finalized"]
        else:
            raise AssertionError(f"Unregistered synthetic request: {method} {path}")
        lose = self.lose == path

        class Response:
            def __init__(self, response_status: int) -> None:
                self.status = response_status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self):
                if method == "POST" and path == "/operations":
                    owner.start_entered.set()
                    if owner.wait_start is not None:
                        await owner.wait_start.wait()
                if lose:
                    raise TimeoutError("Synthetic reply lost after participant accepted")
                return copy.deepcopy(payload)

        owner = self
        return Response(status)


class SyntheticOAuth:
    def __init__(self):
        self.starts = []
        self.observations = []
        self.status = "pending"

    async def start_oauth(self, request):
        self.starts.append(request)
        return OauthStartResponse(
            flow_id="synthetic-oauth",
            method="device",
            verification_url="https://auth.openai.com/codex/device",
            user_code="TEST-CODE",
            expires_in_seconds=600,
        )

    async def oauth_status(self, flow_id=None):
        self.observations.append(flow_id)
        return OauthStatusResponse(status=self.status)

    async def current_device_flow_id(self):
        return None


@dataclass
class Integration:
    client: httpx.AsyncClient
    sessions: async_sessionmaker
    wire: SyntheticWire
    oauth: SyntheticOAuth
    catalog: MemberAuthHandoffCatalog
    statements: list[str]

    async def account(self, account_id):
        async with self.sessions() as session:
            return await session.get(Account, account_id)

    async def verify_incoming(self):
        target = self.catalog.entries[0]
        async with self.sessions() as session:
            session.add(make_account("incoming", target))
            await session.commit()
        self.oauth.status = "success"

    async def create(self):
        target = self.catalog.entries[0]
        response = await self.client.post(
            ROOT,
            json={
                "runId": str(uuid4()),
                "workspaceId": target.workspace_id,
                "presetId": target.preset_id,
                "catalogFingerprint": self.catalog.fingerprint(),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def command(self, run, action, *, expected=200, command_id=None):
        response = await self.client.post(
            f"{ROOT}/{run['id']}/commands",
            json={"action": action, "expectedRevision": run["revision"], "commandId": command_id or str(uuid4())},
        )
        assert response.status_code == expected, response.text
        return response.json()

    async def read(self, run):
        response = await self.client.get(f"{ROOT}/{run['id']}")
        assert response.status_code == 200, response.text
        return response.json()


def make_account(account_id, entry):
    return Account(
        id=account_id,
        email=entry.email,
        chatgpt_account_id=entry.workspace_account_id,
        chatgpt_user_id=entry.user_id,
        plan_type="team",
        status=AccountStatus.ACTIVE,
        last_refresh=datetime(2026, 9, 1, tzinfo=timezone.utc),
        access_token_encrypted=b"SYNTHETIC",
        refresh_token_encrypted=b"SYNTHETIC",
        id_token_encrypted=b"SYNTHETIC",
    )


@pytest_asyncio.fixture
async def integration(tmp_path, monkeypatch):
    fixture_path = Path(
        os.environ.get(
            "MEMBER_SWITCH_WIRE_FIXTURE", str(Path(__file__).parents[1] / "fixtures/member_switch_wire.json")
        )
    )
    examples = json.loads(fixture_path.read_text())
    workspace = examples["catalog"]["workspaces"][0]
    catalog = MemberAuthHandoffCatalog(
        tuple(
            MemberAuthHandoffCatalogEntry(
                preset_id=member["presetId"],
                workspace_id=workspace["id"],
                owner_email=workspace["ownerEmail"],
                workspace_account_id=workspace["workspaceAccountId"],
                email=member["email"],
                user_id=member["userId"],
            )
            for member in workspace["members"]
        )
    )
    assert catalog.fingerprint() == examples["catalog"]["catalogFingerprint"]
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'integrated.sqlite'}")
    statements = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda connection, cursor, statement, parameters, context, many: statements.append(statement),
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add(make_account("outgoing", catalog.entries[1]))
        await session.commit()
    wire, oauth = SyntheticWire(examples), SyntheticOAuth()
    monkeypatch.setattr(dependencies.db_session, "SessionLocal", sessions)
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(
            data_dir=tmp_path,
            companion_account_pool_url="http://host.docker.internal:53418/member-switch/v1/account-pool",
        ),
    )
    monkeypatch.setattr(dependencies, "OauthService", lambda *args, **kwargs: oauth)
    monkeypatch.setattr("app.modules.member_switch.companion.aiohttp.ClientSession", wire.session)

    async def request_session():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.include_router(auth_router)
    app.add_exception_handler(ControlConflict, handle_control_conflict)
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_permission(Permission.ACCOUNTS_WRITE)] = lambda: None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://synthetic.test"
        ) as client:
            yield Integration(client, sessions, wire, oauth, catalog, statements)
    finally:
        await engine.dispose()


async def prepare(integration):
    run = await integration.create()
    for action in ("start", "observe_membership", "prepare_session", "prepare_auth"):
        run = await integration.command(run, action)
    assert run["phase"] == "auth_prepared"
    return run


async def test_manual_lifecycle_uses_real_accounts_and_request_scoped_dependencies(integration):
    run = await prepare(integration)
    old = await integration.account("outgoing")
    assert old.status == AccountStatus.PAUSED and old.deactivation_reason == "member_auth_handoff_quarantine"
    assert len(integration.oauth.starts) == 1
    run = await integration.command(run, "open_browser")
    await integration.verify_incoming()
    calls = list(integration.wire.calls)
    integration.statements.clear()
    for _ in range(3):
        assert await integration.read(run) == run
        response = await integration.client.get("/api/member-auth-handoffs/" + run["handoffId"])
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["state"] == "device_code_issued"
    assert integration.wire.calls == calls and integration.oauth.observations == []
    assert integration.statements and all(sql.lstrip().upper().startswith("SELECT") for sql in integration.statements)
    assert await integration.account("outgoing") is not None
    run = await integration.command(run, "advance_auth")
    assert run["phase"] == "auth_confirmed"
    assert await integration.account("outgoing") is None
    assert (await integration.account("incoming")).status == AccountStatus.ACTIVE
    assert "finish" not in run["allowedActions"]
    for action in ("close_browser", "finish"):
        run = await integration.command(run, action)
    assert run["phase"] == "completed"
    assert (await integration.client.get(ROOT + "/active")).json() == {"run": None}


async def test_actual_companion_unavailable_page_receipt_allows_explicit_cleanup(integration):
    run = await prepare(integration)
    integration.wire.unavailable_page = True
    run = await integration.command(run, "open_browser")
    assert run["browserOperationId"] is not None and run["pendingAction"] is None
    assert run["lastCode"] == "verification_page_unavailable"
    assert "close_browser" in run["allowedActions"] and "finish" not in run["allowedActions"]
    run = await integration.command(run, "close_browser")
    assert run["phase"] == "needs_attention"
    assert "prepare_session" in run["allowedActions"] and "open_browser" not in run["allowedActions"]
    run = await integration.command(run, "prepare_session")
    assert "open_browser" in run["allowedActions"]


async def test_lost_start_body_recovers_by_receipt_without_second_start(integration):
    run = await integration.create()
    integration.wire.lose = "/operations"
    await integration.command(run, "start", expected=409)
    run = await integration.read(run)
    assert run["pendingAction"] == "start"
    run = await integration.command(run, "reconcile")
    assert run["phase"] == "membership_confirmed"
    assert sum(method == "POST" and path == "/operations" for method, path, _ in integration.wire.calls) == 1


async def test_raw_auth_prepare_cannot_bypass_run_admission(integration):
    target = integration.catalog.entries[0]
    response = await integration.client.post(
        "/api/member-auth-handoffs",
        json={
            "memberSwitchOperationId": "old-operation",
            "presetId": target.preset_id,
            "workspaceAccountId": target.workspace_account_id,
            "targetEmail": target.email,
            "targetUserId": target.user_id,
            "membershipState": "active",
            "catalogFingerprint": integration.catalog.fingerprint(),
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "managed_run_command_required"
    assert integration.oauth.starts == [] and integration.wire.calls == []
    assert (await integration.account("outgoing")).status == AccountStatus.ACTIVE


async def test_two_route_requests_share_one_admission_and_do_not_repeat_start(integration):
    run = await integration.create()
    integration.wire.wait_start = asyncio.Event()
    first = asyncio.create_task(integration.command(run, "start"))
    try:
        await asyncio.wait_for(integration.wire.start_entered.wait(), timeout=5)
        rejected = await integration.command(run, "start", expected=409)
        assert rejected["error"]["code"] == "revision_conflict"
    finally:
        integration.wire.wait_start.set()
        result = await first
    assert result["phase"] == "membership_requested"
    assert sum(method == "POST" and path == "/operations" for method, path, _ in integration.wire.calls) == 1


async def test_completed_auth_child_recovers_after_parent_write_failure_without_repeating_delete(
    integration, monkeypatch
):
    run = await prepare(integration)
    await integration.verify_incoming()
    original = MemberSwitchControlRepository.save

    async def lose_parent(self, current, payload, **kwargs):
        if current.kind == "run" and current.pending_action == "advance_auth" and kwargs.get("complete"):
            raise OSError("Synthetic parent write failure after child completion")
        return await original(self, current, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(MemberSwitchControlRepository, "save", lose_parent)
        response = await integration.client.post(
            f"{ROOT}/{run['id']}/commands",
            json={"commandId": str(uuid4()), "expectedRevision": run["revision"], "action": "advance_auth"},
        )
    assert response.status_code == 500
    assert await integration.account("outgoing") is None
    run = await integration.read(run)
    assert run["pendingAction"] == "advance_auth"
    observations = list(integration.oauth.observations)
    run = await integration.command(run, "reconcile")
    assert run["phase"] == "auth_confirmed" and run["pendingAction"] is None
    assert integration.oauth.observations == observations


async def test_lost_finalize_reply_uses_tombstone_not_another_finalize(integration):
    run = await prepare(integration)
    await integration.verify_incoming()
    run = await integration.command(run, "advance_auth")
    integration.wire.lose = f"/operations/{run['operationId']}/finalize"
    await integration.command(run, "finish", expected=409)
    run = await integration.read(run)
    assert run["pendingAction"] == "finish"
    run = await integration.command(run, "reconcile")
    assert run["phase"] == "completed"
    assert sum(path.endswith("/finalize") for _, path, _ in integration.wire.calls) == 1


async def test_release_pending_finish_reconcile_only_repeats_local_finalize(integration):
    run = await prepare(integration)
    await integration.verify_incoming()
    run = await integration.command(run, "advance_auth")
    integration.wire.interrupt_finalize_once = True
    integration.wire.lose = f"/operations/{run['operationId']}/finalize"
    await integration.command(run, "finish", expected=409)
    run = await integration.read(run)
    assert run["pendingAction"] == "finish"
    integration.wire.lose = None
    run = await integration.command(run, "reconcile")
    assert run["phase"] == "completed" and run["pendingAction"] is None
    assert sum(path.endswith("/finalize") for _, path, _ in integration.wire.calls) == 2
    assert sum(path == "/operations" for _, path, _ in integration.wire.calls) == 1


async def test_duplicate_advance_returns_stored_result_without_more_oauth_or_database_mutation(integration):
    run = await prepare(integration)
    await integration.verify_incoming()
    command_id = str(uuid4())
    done = await integration.command(run, "advance_auth", command_id=command_id)
    observations = list(integration.oauth.observations)
    integration.statements.clear()
    assert await integration.command(run, "advance_auth", command_id=command_id) == done
    assert integration.oauth.observations == observations
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in integration.statements)


@pytest.mark.parametrize("missing_outcome_field", [False, True])
async def test_ambiguous_browser_reply_never_enables_a_second_open(integration, missing_outcome_field):
    run = await prepare(integration)
    if missing_outcome_field:
        integration.wire.examples["browser"].pop("outcomeUnknown", None)
    else:
        integration.wire.unknown_browser_outcome = True
    await integration.command(run, "open_browser", expected=409)
    run = await integration.read(run)
    assert run["phase"] == "outcome_unknown" and run["pendingAction"] == "open_browser"
    assert run["allowedActions"] == ["reconcile"]
    await integration.command(run, "open_browser", expected=409)
    assert (
        sum(
            path == "/participant-commands" and body["action"] == "open_browser"
            for _, path, body in integration.wire.calls
        )
        == 1
    )


@pytest.mark.parametrize(
    "action,phase",
    [
        ("prepare_session", "session_prepared"),
        ("open_browser", "auth_browser_opened"),
        ("close_browser", "needs_attention"),
    ],
)
async def test_participant_reply_loss_is_reconciled_through_routes_without_replay(integration, action, phase):
    run = await integration.create()
    for step in ("start", "observe_membership", "prepare_session", "prepare_auth", "open_browser"):
        if step == action:
            break
        run = await integration.command(run, step)
    integration.wire.lose = "/participant-commands"
    await integration.command(run, action, expected=409)
    run = await integration.read(run)
    assert run["pendingAction"] == action
    effect_post_count = sum(
        method == "POST" and path == "/participant-commands" for method, path, _ in integration.wire.calls
    )
    oauth_starts = len(integration.oauth.starts)
    run = await integration.command(run, "reconcile")
    assert run["phase"] == phase and run["pendingAction"] is None
    assert (
        sum(method == "POST" and path == "/participant-commands" for method, path, _ in integration.wire.calls)
        == effect_post_count
    )
    assert len(integration.oauth.starts) == oauth_starts
    assert (await integration.client.get(ROOT + "/active")).json()["run"]["id"] == run["id"]
    if action == "prepare_session":
        assert integration.oauth.starts == []
        assert (await integration.account("outgoing")).status == AccountStatus.ACTIVE
