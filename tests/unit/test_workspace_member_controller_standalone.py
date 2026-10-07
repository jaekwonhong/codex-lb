from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.workspace_member_controller.binding_repository import (
    FileWorkspaceMemberAccountBindingRepository,
)
from app.modules.workspace_member_controller.companion_read_adapter import CompanionHttpReadAdapter
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationAction,
    MembershipMutationCommand,
    MembershipMutationSpec,
    MembershipMutationView,
    MembershipSubject,
)
from app.modules.workspace_member_controller.opencodex_adapter import OpenCodexHttpAccountStateAdapter
from app.modules.workspace_member_controller.read_service import WorkspaceMemberControllerReadService
from app.modules.workspace_member_controller.sql_read_persistence import (
    REQUIRED_CONTROLLER_TABLES,
    SqlMembershipOperationJournalReader,
    SqlWorkspaceIntentReader,
    validate_controller_schema,
)
from app.modules.workspace_member_controller.standalone_app import create_standalone_app
from app.modules.workspace_member_controller.standalone_runtime import (
    ControllerStandaloneRuntime,
    ReadinessReport,
)
from app.modules.workspace_member_controller.standalone_settings import StandaloneSettings

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)


def settings(
    tmp_path: Path,
    *,
    host: str = "127.0.0.1",
    mutations_enabled: bool = False,
) -> StandaloneSettings:
    return StandaloneSettings(
        host=host,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'controller.sqlite3'}"),
        account_bindings_path=tmp_path / "bindings.json",
        admin_token=SecretStr("a" * 48),
        opencodex_admin_token=SecretStr("o" * 48),
        mutations_enabled=mutations_enabled,
    )


def catalog_payload() -> dict:
    return {
        "enabled": True,
        "schemaVersion": 1,
        "catalogFingerprint": "c" * 64,
        "capabilities": [],
        "workspaces": [
            {
                "id": "workspace-1",
                "workspaceAccountId": "workspace-account-1",
                "workspaceName": "Workspace One",
                "ownerEmail": "owner@example.com",
                "members": [
                    {
                        "presetId": "member-1",
                        "displayName": "Member One",
                        "email": "member@example.com",
                        "userId": "user-Member1",
                    }
                ],
                "currentMembers": [],
                "membershipCode": "not_checked",
            }
        ],
    }


def account_state_payload(**overrides) -> dict:
    payload = {
        "schemaVersion": 1,
        "provider": "openai",
        "accountId": "acct-member-1",
        "isMain": False,
        "credentialGeneration": 3,
        "observedAt": int(NOW.timestamp() * 1000),
        "hasCredential": True,
        "needsReauth": False,
        "paused": False,
        "healthStatus": "healthy",
        "selectionState": "selectable",
        "exclusionReasons": [],
        "quotaState": "available",
        "quotaObservedAt": int(NOW.timestamp() * 1000),
        "quotaWindows": [],
        "cooldowns": [],
        "stateRevision": "d" * 64,
    }
    payload.update(overrides)
    return payload


def write_bindings(path: Path, *, account_id: str = "acct-member-1", user_id: str = "user-Member1") -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "bindings": [
                    {
                        "schemaVersion": 1,
                        "workspaceId": "workspace-1",
                        "workspaceAccountId": "workspace-account-1",
                        "presetId": "member-1",
                        "memberUserId": user_id,
                        "memberEmailNormalized": "member@example.com",
                        "role": "member",
                        "opencodexAccountId": account_id,
                        "establishedAt": NOW.isoformat().replace("+00:00", "Z"),
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def write_empty_bindings(path: Path) -> None:
    path.write_text(json.dumps({"schemaVersion": 1, "bindings": []}) + "\n", encoding="utf-8")


async def create_controller_tables(engine) -> None:
    ddl = {
        "member_switch_control_records": """
            CREATE TABLE member_switch_control_records (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, active_scope TEXT,
                revision INTEGER NOT NULL, payload TEXT NOT NULL,
                pending_action TEXT, command_id TEXT, command_hash TEXT
            )
        """,
        "member_switch_command_receipts": """
            CREATE TABLE member_switch_command_receipts (
                record_id TEXT NOT NULL, command_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                PRIMARY KEY (record_id, command_id)
            )
        """,
        "member_rotation_workspace_controls": """
            CREATE TABLE member_rotation_workspace_controls (
                workspace_id TEXT PRIMARY KEY, workspace_account_id TEXT NOT NULL,
                automatic_rotation_enabled INTEGER NOT NULL, version INTEGER NOT NULL,
                updated_at TEXT
            )
        """,
        "member_rotation_quota_operations": """
            CREATE TABLE member_rotation_quota_operations (
                operation_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                workspace_account_id TEXT NOT NULL,
                rotation_event_id TEXT,
                requested_at TEXT NOT NULL,
                initial_admission_code TEXT NOT NULL,
                reserved_at TEXT,
                remove_requested_at TEXT,
                remove_effect TEXT NOT NULL,
                remove_effect_at TEXT,
                invite_requested_at TEXT,
                invite_effect TEXT NOT NULL,
                invite_effect_at TEXT,
                completed_at TEXT,
                reservation_released_at TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """,
        "workspace_member_usage_reset_invalidations": (
            "CREATE TABLE workspace_member_usage_reset_invalidations (id INTEGER PRIMARY KEY)"
        ),
        "workspace_member_final_usage_snapshots": (
            "CREATE TABLE workspace_member_final_usage_snapshots (id INTEGER PRIMARY KEY)"
        ),
    }
    assert set(ddl) == REQUIRED_CONTROLLER_TABLES
    async with engine.begin() as connection:
        for sql in ddl.values():
            await connection.execute(text(sql))


def mock_transport(*, account_states: list[dict] | None = None) -> httpx.MockTransport:
    projected_states = list(account_states or [account_state_payload()])
    account_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal account_reads
        if request.url.host == "127.0.0.1" and request.url.port == 53418:
            assert request.headers["host"] == "127.0.0.1:53418"
            assert request.headers["origin"] == "http://127.0.0.1:2456"
            assert request.headers["x-member-switch-protocol"] == "managed_member_switch_v1"
            if request.url.path == "/member-switch/v1/catalog":
                return httpx.Response(200, json=catalog_payload())
        if request.url.host == "127.0.0.1" and request.url.port == 10101:
            if request.url.path == "/readyz":
                return httpx.Response(200, json={"service": "opencodex", "status": "ready"})
            assert request.headers["authorization"] == "Bearer " + "o" * 48
            if request.url.path == "/api/codex-auth/controller-account-state":
                assert request.url.params["accountId"] == "acct-member-1"
                index = min(account_reads, len(projected_states) - 1)
                account_reads += 1
                return httpx.Response(200, json=projected_states[index])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def build_runtime(
    tmp_path: Path,
    *,
    account_states: list[dict] | None = None,
    mutations_enabled: bool = False,
    mutation_service=None,
) -> ControllerStandaloneRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    configured = settings(tmp_path, mutations_enabled=mutations_enabled)
    write_bindings(configured.account_bindings_path)
    engine = create_async_engine(configured.resolved_database_url())
    await create_controller_tables(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    client = httpx.AsyncClient(transport=mock_transport(account_states=account_states))
    reads = CompanionHttpReadAdapter(base_url=configured.companion_base_url, client=client)
    states = OpenCodexHttpAccountStateAdapter(
        base_url=configured.opencodex_management_base_url,
        admin_token=configured.resolved_opencodex_admin_token(),
        client=client,
    )
    bindings = FileWorkspaceMemberAccountBindingRepository(configured.account_bindings_path)
    service = WorkspaceMemberControllerReadService(
        reads,
        SqlWorkspaceIntentReader(sessions),
        SqlMembershipOperationJournalReader(sessions),
    )
    return ControllerStandaloneRuntime(
        settings=configured,
        engine=engine,
        http=client,
        bindings=bindings,
        reads=reads,
        account_states=states,
        read_service=service,
        mutation_service=mutation_service,
        now_ms=lambda: int(NOW.timestamp() * 1000),
    )


def mutation_command(action: MembershipMutationAction = "switch") -> MembershipMutationCommand:
    incoming = MembershipSubject(
        preset_id="member-1",
        email="member@example.com",
        user_id="user-Member1",
    )
    outgoing = MembershipSubject(
        preset_id="member-old",
        email="old@example.com",
        user_id="user-Old",
    )
    return MembershipMutationCommand(
        operation_id="11111111-1111-4111-8111-111111111111",
        command_id="22222222-2222-4222-8222-222222222222",
        expected_revision=0,
        mutation=MembershipMutationSpec(
            action=action,
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="c" * 64,
            incoming=incoming if action in {"add", "switch"} else None,
            outgoing=outgoing if action in {"remove", "switch"} else None,
        ),
    )


class FakeMutationService:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    @staticmethod
    def view(command: MembershipMutationCommand) -> MembershipMutationView:
        return MembershipMutationView(
            operation_id=str(command.operation_id),
            revision=0,
            mutation=command.mutation,
            phase="ready",
            last_code="mutation_ready",
            updated_at=NOW,
        )

    async def submit(self, command: MembershipMutationCommand) -> MembershipMutationView:
        self.calls.append(("submit", command))
        return self.view(command)

    async def get(self, operation_id: str) -> MembershipMutationView | None:
        self.calls.append(("get", operation_id))
        return self.view(mutation_command())

    async def reconcile(self, operation_id: str) -> MembershipMutationView:
        self.calls.append(("reconcile", operation_id))
        return self.view(mutation_command())


def test_settings_require_secret_sources_and_loopback_listener(tmp_path):
    with pytest.raises(ValidationError, match="admin_token_requires_exactly_one_source"):
        StandaloneSettings(
            database_url=SecretStr("sqlite+aiosqlite:////tmp/x.db"),
            account_bindings_path=tmp_path / "bindings.json",
            opencodex_admin_token=SecretStr("o" * 48),
        )
    with pytest.raises(ValidationError, match="non_loopback_bind_requires_explicit_opt_in"):
        settings(tmp_path, host="0.0.0.0")
    container_settings = StandaloneSettings(
        host="0.0.0.0",
        allow_non_loopback_bind=True,
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'container.sqlite3'}"),
        account_bindings_path=tmp_path / "bindings.json",
        admin_token=SecretStr("a" * 48),
        opencodex_admin_token=SecretStr("o" * 48),
    )
    assert container_settings.host == "0.0.0.0"
    with pytest.raises(ValidationError, match="account_bindings_path_must_be_absolute"):
        StandaloneSettings(
            database_url=SecretStr("sqlite+aiosqlite:////tmp/x.db"),
            account_bindings_path=Path("relative-bindings.json"),
            admin_token=SecretStr("a" * 48),
            opencodex_admin_token=SecretStr("o" * 48),
        )
    configured = settings(tmp_path)
    configured.database_url = SecretStr("sqlite+aiosqlite:///:memory:")
    with pytest.raises(ValueError, match="controller_database_must_be_durable"):
        configured.resolved_database_url()


def test_binding_file_is_explicit_exact_and_rejects_conflicting_subject_reuse(tmp_path):
    configured = settings(tmp_path)
    write_bindings(configured.account_bindings_path)
    repository = FileWorkspaceMemberAccountBindingRepository(configured.account_bindings_path)
    snapshot = repository.snapshot()
    assert snapshot.bindings[0].opencodex_account_id == "acct-member-1"

    payload = json.loads(configured.account_bindings_path.read_text())
    second = dict(payload["bindings"][0])
    second["workspaceId"] = "workspace-2"
    second["workspaceAccountId"] = "workspace-account-2"
    second["presetId"] = "member-2"
    second["memberUserId"] = "user-Different"
    payload["bindings"].append(second)
    configured.account_bindings_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="account_binding_file_invalid"):
        repository.snapshot()


def test_secret_files_require_owner_only_permissions(tmp_path):
    admin = tmp_path / "admin-token"
    opencodex = tmp_path / "opencodex-token"
    admin.write_text("a" * 48 + "\n")
    opencodex.write_text("o" * 48 + "\n")
    os.chmod(admin, 0o600)
    os.chmod(opencodex, 0o600)
    configured = StandaloneSettings(
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'controller.sqlite3'}"),
        account_bindings_path=tmp_path / "bindings.json",
        admin_token_file=admin,
        opencodex_admin_token_file=opencodex,
    )
    assert configured.resolved_admin_token() == "a" * 48
    assert configured.resolved_opencodex_admin_token() == "o" * 48

    os.chmod(admin, 0o644)
    with pytest.raises(ValueError, match="admin_token_file_permissions_too_open"):
        configured.resolved_admin_token()


async def test_sql_read_persistence_validates_schema_and_reads_intent_and_active_operation(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'controller.sqlite3'}")
    await create_controller_tables(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO member_rotation_workspace_controls "
                "(workspace_id, workspace_account_id, automatic_rotation_enabled, version, updated_at) "
                "VALUES ('workspace-1', 'workspace-account-1', 1, 4, '2026-10-06T11:00:00+00:00')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO member_switch_control_records "
                "(id, kind, active_scope, revision, payload, pending_action, command_id, command_hash) "
                "VALUES ('op-1', 'controller_membership_mutation', 'member-switch', 3, '{}', 'switch', 'cmd-1', 'x')"
            )
        )
    await validate_controller_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    intent = await SqlWorkspaceIntentReader(sessions).get(
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
    )
    active = await SqlMembershipOperationJournalReader(sessions).active()
    assert intent.enabled is True and intent.version == 4
    assert active is not None and active.operation_id == "op-1" and active.pending_action == "switch"
    await engine.dispose()


async def test_schema_validation_rejects_reachable_but_stale_controller_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stale.sqlite3'}")
    await create_controller_tables(engine)
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE member_rotation_workspace_controls"))
        await connection.execute(
            text(
                "CREATE TABLE member_rotation_workspace_controls ("
                "workspace_id TEXT PRIMARY KEY, workspace_account_id TEXT NOT NULL, "
                "automatic_rotation_enabled INTEGER NOT NULL, version INTEGER NOT NULL)"
            )
        )
    with pytest.raises(RuntimeError, match="controller_schema_columns_missing:member_rotation_workspace_controls"):
        await validate_controller_schema(engine)
    await engine.dispose()


async def test_standalone_runtime_startup_validates_db_companion_binding_and_opencodex(tmp_path):
    runtime = await build_runtime(tmp_path)
    try:
        report = await runtime.startup()
        assert report.ready is True
        assert report.workspace_count == 1
        assert report.binding_count == 1
        assert report.opencodex_account_count == 1
    finally:
        await runtime.close()


async def test_standalone_runtime_rejects_unstable_or_stale_bound_account_projection(tmp_path):
    unstable = await build_runtime(
        tmp_path / "unstable",
        account_states=[
            account_state_payload(stateRevision="d" * 64),
            account_state_payload(stateRevision="e" * 64),
        ],
    )
    try:
        with pytest.raises(RuntimeError, match="startup_opencodex_account_state_unstable"):
            await unstable.startup()
    finally:
        await unstable.close()

    stale = await build_runtime(
        tmp_path / "stale",
        account_states=[
            account_state_payload(observedAt=int(NOW.timestamp() * 1000) - 31_000),
        ],
    )
    try:
        with pytest.raises(RuntimeError, match="startup_opencodex_account_state_stale"):
            await stale.startup()
    finally:
        await stale.close()


async def test_standalone_runtime_keeps_stable_excluded_binding_readiness_valid(tmp_path):
    runtime = await build_runtime(
        tmp_path,
        account_states=[
            account_state_payload(
                needsReauth=True,
                paused=True,
                selectionState="excluded",
                exclusionReasons=["paused", "needs_reauth"],
                quotaState="exhausted",
            )
        ],
    )
    try:
        report = await runtime.startup()
        assert report.ready is True
        assert report.binding_count == 1
        assert report.opencodex_account_count == 1
    finally:
        await runtime.close()


async def test_empty_binding_shadow_still_requires_opencodex_ready(tmp_path):
    runtime = await build_runtime(tmp_path)
    write_empty_bindings(runtime.settings.account_bindings_path)
    try:
        report = await runtime.startup()
        assert report.binding_count == 0
        assert report.opencodex_account_count == 0
    finally:
        await runtime.close()


async def test_standalone_http_surface_has_public_health_admin_read_only_v1_and_no_mutations(tmp_path):
    runtime = await build_runtime(tmp_path)
    app = create_standalone_app(runtime.settings, runtime)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://controller") as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            denied = await client.get("/v1/catalog")
            allowed = await client.get(
                "/v1/catalog",
                headers={"Authorization": "Bearer " + "a" * 48},
            )
            mutation = await client.post(
                "/v1/workspaces/workspace-1/members",
                headers={"Authorization": "Bearer " + "a" * 48},
                json={},
            )
            docs = await client.get("/docs")
            openapi = await client.get("/openapi.json")

    assert live.status_code == 200
    assert ready.status_code == 200
    assert "catalogFingerprint" not in ready.json()
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert mutation.status_code == 404
    assert docs.status_code == 404
    assert openapi.status_code == 404
    methods = {
        method
        for route in app.routes
        for method in getattr(route, "methods", set())
        if getattr(route, "path", "").startswith("/v1")
    }
    assert methods <= {"GET", "HEAD"}


async def test_mutation_enabled_surface_is_admin_only_and_switch_only(tmp_path):
    mutations = FakeMutationService()
    runtime = await build_runtime(
        tmp_path,
        mutations_enabled=True,
        mutation_service=mutations,
    )
    app = create_standalone_app(runtime.settings, runtime)
    headers = {"Authorization": "Bearer " + "a" * 48}
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://controller") as client:
            denied = await client.post("/v1/mutations", json=mutation_command().model_dump(mode="json", by_alias=True))
            unsupported = await client.post(
                "/v1/mutations",
                headers=headers,
                json=mutation_command("add").model_dump(mode="json", by_alias=True),
            )
            submitted = await client.post(
                "/v1/mutations",
                headers=headers,
                json=mutation_command().model_dump(mode="json", by_alias=True),
            )
            fetched = await client.get(
                "/v1/mutations/11111111-1111-4111-8111-111111111111",
                headers=headers,
            )
            reconciled = await client.post(
                "/v1/mutations/11111111-1111-4111-8111-111111111111/reconcile",
                headers=headers,
            )

    assert denied.status_code == 401
    assert unsupported.status_code == 409
    assert unsupported.json()["detail"]["code"] == "mutation_action_not_qualified"
    assert submitted.status_code == 200
    assert fetched.status_code == 200
    assert reconciled.status_code == 200
    assert [kind for kind, _ in mutations.calls] == ["submit", "get", "reconcile"]


async def test_mutation_enabled_runtime_rejects_read_only_database(tmp_path):
    runtime = await build_runtime(
        tmp_path,
        mutations_enabled=True,
        mutation_service=FakeMutationService(),
    )

    @event.listens_for(runtime.engine.sync_engine, "connect")
    def _read_only(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA query_only = 1")

    await runtime.engine.dispose()
    try:
        with pytest.raises(RuntimeError, match="startup_mutation_database_read_only"):
            await runtime.startup()
    finally:
        await runtime.close()


async def test_runtime_startup_rejects_binding_that_no_longer_matches_catalog(tmp_path):
    runtime = await build_runtime(tmp_path)
    write_bindings(runtime.settings.account_bindings_path, user_id="user-Wrong")
    try:
        with pytest.raises(RuntimeError, match="startup_account_binding_member_mismatch"):
            await runtime.startup()
    finally:
        await runtime.close()


async def test_app_closes_runtime_when_startup_validation_fails(tmp_path):
    configured = settings(tmp_path)

    class FailingRuntime:
        def __init__(self):
            self.closed = False
            self.read_service = None

        async def startup(self):
            raise RuntimeError("startup_failed")

        async def readiness(self):
            return ReadinessReport(True, "c" * 64, 0, 0, 0)

        async def close(self):
            self.closed = True

    runtime = FailingRuntime()
    app = create_standalone_app(configured, cast(ControllerStandaloneRuntime, runtime))
    with pytest.raises(RuntimeError, match="startup_failed"):
        async with app.router.lifespan_context(app):
            pass
    assert runtime.closed is True
