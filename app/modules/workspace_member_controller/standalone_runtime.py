from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.modules.workspace_member_controller.account_state import (
    OpenCodexAccountStateError,
    read_stable_account_state,
)
from app.modules.workspace_member_controller.binding_repository import (
    FileWorkspaceMemberAccountBindingRepository,
)
from app.modules.workspace_member_controller.companion_read_adapter import CompanionHttpReadAdapter
from app.modules.workspace_member_controller.domain import Catalog
from app.modules.workspace_member_controller.opencodex_adapter import OpenCodexHttpAccountStateAdapter
from app.modules.workspace_member_controller.read_service import WorkspaceMemberControllerReadService
from app.modules.workspace_member_controller.sql_read_persistence import (
    SqlMembershipOperationJournalReader,
    SqlWorkspaceIntentReader,
    validate_controller_schema,
)
from app.modules.workspace_member_controller.standalone_settings import StandaloneSettings

if TYPE_CHECKING:
    from app.modules.workspace_member_controller.mutation_service import WorkspaceMembershipMutationService


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    catalog_fingerprint: str
    workspace_count: int
    binding_count: int
    opencodex_account_count: int


class ControllerStandaloneRuntime:
    _ACCOUNT_STATE_MAX_AGE_MS = 30_000

    def __init__(
        self,
        *,
        settings: StandaloneSettings,
        engine: AsyncEngine,
        http: httpx.AsyncClient,
        bindings: FileWorkspaceMemberAccountBindingRepository,
        reads: CompanionHttpReadAdapter,
        account_states: OpenCodexHttpAccountStateAdapter,
        read_service: WorkspaceMemberControllerReadService,
        mutation_service: WorkspaceMembershipMutationService | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.http = http
        self.bindings = bindings
        self.reads = reads
        self.account_states = account_states
        self.read_service = read_service
        self.mutation_service = mutation_service
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._startup_report: ReadinessReport | None = None

    @classmethod
    def build(cls, settings: StandaloneSettings) -> ControllerStandaloneRuntime:
        database_url = settings.resolved_database_url()
        opencodex_admin_token = settings.resolved_opencodex_admin_token()
        http = httpx.AsyncClient(trust_env=False)
        engine = create_async_engine(database_url, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        bindings = FileWorkspaceMemberAccountBindingRepository(settings.account_bindings_path)
        reads = CompanionHttpReadAdapter(base_url=settings.companion_base_url, client=http)
        account_states = OpenCodexHttpAccountStateAdapter(
            base_url=settings.opencodex_management_base_url,
            admin_token=opencodex_admin_token,
            client=http,
        )
        read_service = WorkspaceMemberControllerReadService(
            reads,
            SqlWorkspaceIntentReader(sessions),
            SqlMembershipOperationJournalReader(sessions),
        )
        mutation_service = None
        if settings.mutations_enabled:
            from app.modules.workspace_member_controller.legacy_production_runtime import (
                build_legacy_production_mutation_service,
            )

            mutation_service = build_legacy_production_mutation_service(
                settings=settings,
                sessions=sessions,
                reads=reads,
            )
        return cls(
            settings=settings,
            engine=engine,
            http=http,
            bindings=bindings,
            reads=reads,
            account_states=account_states,
            read_service=read_service,
            mutation_service=mutation_service,
        )

    async def startup(self) -> ReadinessReport:
        self._startup_report = await self.validate()
        return self._startup_report

    async def validate(self) -> ReadinessReport:
        await validate_controller_schema(self.engine)
        if self.settings.mutations_enabled:
            await self._validate_mutation_writer()
        catalog = await self.reads.catalog()
        await self._validate_opencodex_ready()
        snapshot = self.bindings.snapshot()
        self._validate_binding_catalog(snapshot.bindings, catalog)
        account_ids = sorted({binding.opencodex_account_id for binding in snapshot.bindings})
        for account_id in account_ids:
            try:
                state = await read_stable_account_state(self.account_states, account_id)
            except OpenCodexAccountStateError as exc:
                raise RuntimeError(f"startup_{exc.code}") from exc
            if state.account_id != account_id:
                raise RuntimeError("startup_opencodex_account_identity_mismatch")
            if not state.is_fresh(
                now_ms=self._now_ms(),
                max_age_ms=self._ACCOUNT_STATE_MAX_AGE_MS,
            ):
                raise RuntimeError("startup_opencodex_account_state_stale")
        return ReadinessReport(
            ready=True,
            catalog_fingerprint=catalog.catalog_fingerprint,
            workspace_count=len(catalog.workspaces),
            binding_count=len(snapshot.bindings),
            opencodex_account_count=len(account_ids),
        )

    async def _validate_mutation_writer(self) -> None:
        async with self.engine.connect() as connection:
            dialect = connection.dialect.name
            if dialect == "postgresql":
                read_only = str((await connection.execute(text("SHOW transaction_read_only"))).scalar_one())
                if read_only.casefold() != "off":
                    raise RuntimeError("startup_mutation_database_read_only")
                privileges = (
                    await connection.execute(
                        text(
                            "SELECT "
                            "has_table_privilege(current_user, 'member_switch_control_records', "
                            "'SELECT,INSERT,UPDATE'), "
                            "has_table_privilege(current_user, 'member_switch_command_receipts', 'SELECT,INSERT')"
                        )
                    )
                ).one()
                if not all(bool(value) for value in privileges):
                    raise RuntimeError("startup_mutation_database_privileges_missing")
                return
            if dialect == "sqlite":
                query_only = int((await connection.execute(text("PRAGMA query_only"))).scalar_one())
                if query_only != 0:
                    raise RuntimeError("startup_mutation_database_read_only")
                return
            raise RuntimeError("startup_mutation_database_dialect_unsupported")

    async def _validate_opencodex_ready(self) -> None:
        try:
            response = await self.http.get(
                self.settings.opencodex_management_base_url.rstrip("/") + "/readyz",
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("startup_opencodex_unavailable") from exc
        if response.status_code != 200:
            raise RuntimeError("startup_opencodex_not_ready")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("startup_opencodex_readiness_invalid") from exc
        if not isinstance(payload, dict) or payload.get("service") != "opencodex" or payload.get("status") != "ready":
            raise RuntimeError("startup_opencodex_readiness_invalid")

    async def readiness(self) -> ReadinessReport:
        return await self.validate()

    async def close(self) -> None:
        await self.http.aclose()
        await self.engine.dispose()

    @staticmethod
    def _validate_binding_catalog(bindings, catalog: Catalog) -> None:
        workspaces = {workspace.id: workspace for workspace in catalog.workspaces}
        for binding in bindings:
            workspace = workspaces.get(binding.workspace_id)
            if workspace is None or workspace.workspace_account_id != binding.workspace_account_id:
                raise RuntimeError("startup_account_binding_workspace_mismatch")
            if binding.role == "owner":
                owner = workspace.owner_auth
                if (
                    owner is None
                    or owner.preset_id != binding.preset_id
                    or owner.user_id != binding.member_user_id
                    or owner.email.casefold() != binding.member_email_normalized
                ):
                    raise RuntimeError("startup_account_binding_member_mismatch")
                continue
            matches = [
                member
                for member in workspace.members
                if member.preset_id == binding.preset_id
                and member.user_id == binding.member_user_id
                and member.email.casefold() == binding.member_email_normalized
            ]
            if len(matches) != 1:
                raise RuntimeError("startup_account_binding_member_mismatch")
