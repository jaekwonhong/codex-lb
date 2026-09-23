from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.usage.weekly_observation import RotationUsageObservation, UsageAccountIdentity
from app.db.models import Account
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.member_auth_handoff.rotation_events import RotationQuotaRepository
from app.modules.member_rotation_operator.repository import MemberRotationOperatorRepository
from app.modules.member_switch.rotation_controller import RotationController, rotation_controller_id
from app.modules.member_switch.rotation_foundation import (
    RotationEvaluationIdentity,
    RotationFoundationState,
    bind_rotation_reset_resolution,
    bind_rotation_weekly_evidence,
    build_weekly_recovery_observer,
    evaluate_rotation_foundation,
    reserve_rotation_quota,
)
from app.modules.member_switch.rotation_plan import SCHEDULE_BINDING_ID, CanaryPlan, read_canary_plan
from app.modules.member_switch.runtime_attestation import FileRuntimeAttestation, RuntimeAttestation
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationUsageRefresher,
    build_rotation_usage_refresh_callback,
    resolve_rotation_reset_credit,
)
from app.modules.usage.updater import build_background_usage_updater


class WorkerUsage(RotationUsageRefresher, Protocol):
    async def force_rotation_usage_observation(self, account: Account) -> RotationUsageObservation: ...


@dataclass
class WorkerServices:
    controller: RotationController
    usage: WorkerUsage


class ServicesFactory(Protocol):
    def __call__(
        self, runtime: RuntimeAttestation, guard: Callable[[], Awaitable[None]]
    ) -> AbstractAsyncContextManager[WorkerServices]: ...


@asynccontextmanager
async def production_services(
    runtime: RuntimeAttestation, guard: Callable[[], Awaitable[None]]
) -> AsyncIterator[WorkerServices]:
    from app.dependencies import get_member_auth_handoff_context, get_member_switch_service

    # This is an owned background session, never a request session or shared
    # across concurrent tasks. Controller/quota operations own short sessions.
    async with SessionLocal() as session:
        auth = get_member_auth_handoff_context(session)
        switch = get_member_switch_service(auth)
        controller = RotationController(
            switch.controls,
            switch,
            SessionLocal,
            SessionLocal,
            runtime_attestation=runtime,
            dispatch_guard=guard,
        )
        yield WorkerServices(controller, build_background_usage_updater())


class RotationWorker:
    def __init__(
        self,
        directory: Path,
        *,
        sessions: Callable[[], AsyncSession] = SessionLocal,
        services: ServicesFactory = production_services,
        runtime: RuntimeAttestation | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.directory = directory
        self.sessions = sessions
        self.services = services
        self.clock = clock
        self.runtime = runtime or FileRuntimeAttestation(
            directory, get_settings().companion_account_pool_url, clock=clock
        )

    async def require_plan(self, plan: CanaryPlan) -> None:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if read_canary_plan(self.directory) != plan or self.clock() >= plan.expires_at:
            raise ValueError("rotation_plan_disabled_changed_or_expired")
        async with self.sessions() as session:
            intent = await MemberRotationOperatorRepository(session).intent(
                workspace_id=plan.workspace_id, workspace_account_id=plan.workspace_account_id
            )
        if not intent.enabled:
            raise ValueError("rotation_workspace_disabled")
        # The DB read can wait; a plan switched OFF during that wait must win.
        if read_canary_plan(self.directory) != plan or self.clock() >= plan.expires_at:
            raise ValueError("rotation_plan_disabled_changed_or_expired")

    async def account(self, plan: CanaryPlan) -> Account:
        async with self.sessions() as session:
            accounts = await AccountsRepository(session).list_accounts()
            matches = [
                a
                for a in accounts
                if a.chatgpt_account_id == plan.workspace_account_id
                and a.chatgpt_user_id == plan.outgoing_user_id
                and a.email.casefold() == plan.outgoing_email.casefold()
            ]
            if len(matches) != 1 or matches[0].id != plan.outgoing_account_id:
                raise ValueError("rotation_account_identity_ambiguous")
            account = matches[0]
            session.expunge(account)
            return account

    async def run(self, plan: CanaryPlan) -> None:
        async def guard() -> None:
            await self.require_plan(plan)

        await guard()
        self.runtime.require(plan.provenance)
        async with self.services(self.runtime, guard) as services:
            controller = services.controller
            controls = controller.controls
            binding = await controls.get(SCHEDULE_BINDING_ID)
            if binding is not None and (
                binding.kind != "rotation_schedule"
                or binding.active_scope is not None
                or binding.pending_action
                or CanaryPlan.model_validate_json(binding.payload) != plan
            ):
                raise ValueError("rotation_canary_plan_already_bound")
            existing = await controller.get(rotation_controller_id(str(plan.evaluation_id)))
            if existing is not None:
                if binding is None:
                    raise ValueError("rotation_canary_binding_missing")
                if (
                    existing.workspace_id,
                    existing.workspace_account_id,
                    existing.outgoing_account_id,
                    existing.outgoing_email.casefold(),
                    existing.outgoing_user_id,
                    existing.membership_epoch,
                ) != (
                    plan.workspace_id,
                    plan.workspace_account_id,
                    plan.outgoing_account_id,
                    plan.outgoing_email.casefold(),
                    plan.outgoing_user_id,
                    plan.membership_epoch,
                ):
                    raise ValueError("rotation_controller_plan_mismatch")
                await controller.resume(existing.id, pre_effect_attention=True)
                return
            if binding is not None:
                # Crash after evaluation admission is an unknown reset/evaluation
                # outcome. Do not spend a second credit or manufacture a new UUID.
                raise ValueError("rotation_evaluation_interrupted_requires_attention")

            switch = controller.member_switch
            membership_observed_at: datetime | None = None

            async def current_member() -> UsageAccountIdentity | None:
                nonlocal membership_observed_at
                membership_observed_at = None
                catalog = await switch.refresh_catalog()
                if not catalog.enabled or not {
                    "member_rotation_canary_effect_gate_v1",
                    "member_rotation_managed_remove_telemetry_v1",
                }.issubset(catalog.capabilities):
                    raise ValueError("rotation_canary_capability_required")
                workspaces = [
                    w
                    for w in catalog.workspaces
                    if w.id == plan.workspace_id and w.workspace_account_id == plan.workspace_account_id
                ]
                if len(workspaces) != 1:
                    return None
                workspace = workspaces[0]
                if workspace.membership_observed_at is None or len(workspace.current_members) != 1:
                    return None
                if not timedelta(0) <= self.clock() - workspace.membership_observed_at <= timedelta(seconds=30):
                    return None
                current = workspace.current_members[0]
                if (
                    current.email.casefold() != plan.outgoing_email.casefold()
                    or current.user_id != plan.outgoing_user_id
                    or current.preset_id is None
                ):
                    return None
                await self.account(plan)
                if not timedelta(0) <= self.clock() - workspace.membership_observed_at <= timedelta(seconds=30):
                    return None
                membership_observed_at = workspace.membership_observed_at
                return plan.member

            if await current_member() is None:
                raise ValueError("rotation_current_member_mismatch")
            evaluation = RotationEvaluationIdentity(
                str(plan.evaluation_id),
                plan.workspace_id,
                plan.member,
                str(uuid5(NAMESPACE_URL, f"rotation-reset:{plan.evaluation_id}")),
            )
            started = self.clock()

            async def fetch() -> RotationUsageObservation:
                return await services.usage.force_rotation_usage_observation(await self.account(plan))

            receipt = await fetch()
            weekly = bind_rotation_weekly_evidence(receipt, evaluation, not_before=started)
            if weekly.assess(plan.member, now=self.clock()).state != "exhausted":
                return
            if await current_member() is None:
                raise ValueError("rotation_current_member_changed")
            await guard()
            self.runtime.require(plan.provenance)
            # Unique fixed row admits one evaluation across replicas and restarts.
            await controls.create(SCHEDULE_BINDING_ID, "rotation_schedule", plan.model_dump_json(), own_scope=False)
            account = await self.account(plan)
            await guard()
            self.runtime.require(plan.provenance)
            if weekly.assess(plan.member, now=self.clock()).state != "exhausted":
                raise ValueError("rotation_weekly_expired_before_reset")

            async def require_reset_admission(redeem_account: Account) -> None:
                redeem_identity = UsageAccountIdentity(
                    redeem_account.id,
                    redeem_account.chatgpt_account_id,
                    redeem_account.chatgpt_user_id,
                    redeem_account.email,
                )
                if not redeem_identity.matches(plan.member):
                    raise ValueError("rotation_reset_account_identity_changed")
                if await current_member() is None:
                    raise ValueError("rotation_current_member_changed")
                await guard()
                # Central discovery and pinning, and the guard's own reads, can
                # wait. No asynchronous work separates these checks from consume.
                if membership_observed_at is None or not (
                    timedelta(0) <= self.clock() - membership_observed_at <= timedelta(seconds=30)
                ):
                    raise ValueError("rotation_reset_membership_observation_expired")
                assessment = weekly.assess(plan.member, now=self.clock())
                if assessment.state != "exhausted":
                    raise ValueError(f"rotation_reset_weekly:{assessment.reason or assessment.state}")
                self.runtime.require(plan.provenance)

            resolution = await resolve_rotation_reset_credit(
                account,
                redeem_request_id=evaluation.redeem_request_id,
                observe_fresh_weekly=build_weekly_recovery_observer(
                    fetch,
                    current_member,
                    evaluation=evaluation,
                    not_before=started,
                    clock=self.clock,
                ),
                refresh_usage=build_rotation_usage_refresh_callback(services.usage),
                before_consume=require_reset_admission,
            )
            reset = bind_rotation_reset_resolution(evaluation, resolution)
            # Always refresh after reset resolution, including authoritative no-credit.
            receipt = await fetch()
            weekly = bind_rotation_weekly_evidence(receipt, evaluation, not_before=started)
            if await current_member() is None:
                raise ValueError("rotation_current_member_changed")
            await guard()
            self.runtime.require(plan.provenance)
            foundation = evaluate_rotation_foundation(weekly, current_member=plan.member, now=self.clock(), reset=reset)
            quota = None
            if foundation.state is RotationFoundationState.QUOTA_REQUIRED:
                async with self.sessions() as session:
                    quota = await reserve_rotation_quota(
                        RotationQuotaRepository(session, clock=self.clock),
                        weekly=weekly,
                        reset=reset,
                        current_member=plan.member,
                        now=self.clock(),
                        operation_id=str(uuid5(NAMESPACE_URL, f"rotation-quota:{plan.evaluation_id}")),
                    )
            await controller.evaluate_and_start(
                weekly=weekly,
                reset=reset,
                quota=quota,
                current_member=plan.member,
                final_usage_receipt=receipt,
                membership_epoch=plan.membership_epoch,
                p4_provenance=plan.provenance,
            )
