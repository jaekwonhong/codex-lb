from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.auth.dependencies import require_dashboard_write_access, validate_dashboard_session
from app.db.models import Account, MemberSwitchCommandReceipt, MemberSwitchControlRecord
from app.dependencies import (
    get_member_auth_enrollment_command_service,
    get_member_auth_enrollment_service,
    get_member_switch_controls,
)
from app.modules.member_auth_handoff.schemas import (
    MemberAuthHandoffResponse,
    WorkspaceAuthObservationMember,
    WorkspaceAuthObservationResponse,
)
from app.modules.member_switch.admission import require_new_work_admission
from app.modules.member_switch.api import handle_control_conflict, router
from app.modules.member_switch.auth_enrollment import MemberAuthEnrollmentService
from app.modules.member_switch.repository import (
    ControlConflict,
    ControlRecord,
    MemberSwitchControlRepository,
    command_fingerprint,
)
from app.modules.member_switch.schemas import (
    AuthEnrollmentCommandRequest,
    AuthEnrollmentCreateRequest,
    AuthEnrollmentPostProbe,
    Catalog,
    CompanionAdmission,
    EgoOAuthBrowserResponse,
    EgoOAuthProfileResponse,
    Member,
    MembershipObservation,
    MembershipObservationMember,
    OwnerAuthTarget,
    Workspace,
)
from app.modules.member_switch.service import MemberSwitchService

pytestmark = pytest.mark.unit
WORKSPACE_ID = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"
FINGERPRINT = "a" * 64


class EnrollmentCompanion:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.current_email = "target@example.com"
        self.current_user_id = "user-Target"
        self.can_start = True
        self.browser_outcome = "success"
        self.profile_ready = True
        self.owner_ego_capability = True
        self.owner_oauth_capability = True
        self.owner_auth_available = True
        self.device_auth_automation_capability = True
        self.browser_code = "authorization_complete"
        self.status_code = "authorization_complete"

    async def admission(self) -> CompanionAdmission:
        self.calls.append("admission")
        return CompanionAdmission(can_start=self.can_start, code="ready" if self.can_start else "operation_retained")

    async def catalog(self) -> Catalog:
        self.calls.append("catalog")
        return Catalog(
            enabled=True,
            schema_version=1,
            catalog_fingerprint=FINGERPRINT,
            capabilities=["managed_member_switch_v1"]
            + (["ego_lite_owner_membership_observation_v1"] if self.owner_ego_capability else [])
            + (["ego_lite_device_auth_automation_v1"] if self.device_auth_automation_capability else [])
            + (["ego_lite_owner_oauth_enrollment_v1"] if self.owner_oauth_capability else []),
            workspaces=[
                Workspace(
                    id="workspace-1",
                    workspace_account_id=WORKSPACE_ID,
                    workspace_name="Workspace 1",
                    owner_email="owner@example.com",
                    owner_auth=(
                        OwnerAuthTarget(
                            preset_id="owner:workspace-1",
                            email="owner@example.com",
                            user_id="user-Owner",
                        )
                        if self.owner_auth_available
                        else None
                    ),
                    members=[
                        Member(
                            preset_id="target",
                            display_name="Target",
                            email="target@example.com",
                            user_id="user-Target",
                        )
                    ],
                )
            ],
        )

    async def observe_membership(self, workspace_id: str) -> MembershipObservation:
        self.calls.append("observe_membership:" + workspace_id)
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id="workspace-1",
            workspace_account_id=WORKSPACE_ID,
            catalog_fingerprint=FINGERPRINT,
            observed_at=datetime.now(timezone.utc),
            complete=True,
            owner_verified=True,
            identity_ambiguous=False,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=[
                MembershipObservationMember(
                    email="owner@example.com",
                    user_id="user-Owner",
                    preset_id=None,
                    classification="owner",
                ),
                MembershipObservationMember(
                    email=self.current_email,
                    user_id=self.current_user_id,
                    preset_id="target",
                    classification="managed",
                )
            ],
        )

    async def open_ego_oauth_browser(self, request):
        self.calls.append("open_ego_browser")
        assert request.enrollment_id
        assert request.workspace_id == "workspace-1"
        assert request.workspace_account_id == WORKSPACE_ID
        if request.preset_id == "owner:workspace-1":
            assert request.target_email == "owner@example.com"
            assert request.target_user_id == "user-Owner"
        else:
            assert request.preset_id == "target"
            assert request.target_email == "target@example.com"
            assert request.target_user_id == "user-Target"
        if self.browser_outcome == "unknown":
            return EgoOAuthBrowserResponse(
                accepted=False,
                state="outcome_unknown",
                code="ego_task_space_handoff_failed",
                enrollment_id=request.enrollment_id,
                profile_id="CodexLB-account-target",
                task_space_id=7,
                ownership="agent",
                outcome_unknown=True,
            )
        if self.browser_outcome == "missing":
            return EgoOAuthBrowserResponse(
                accepted=False,
                state="failed",
                code="ego_profile_not_found",
                enrollment_id=request.enrollment_id,
                profile_id="CodexLB-account-target",
            )
        return EgoOAuthBrowserResponse(
            accepted=True,
            state="user_controlled",
            code=self.browser_code,
            enrollment_id=request.enrollment_id,
            profile_id="CodexLB-account-target",
            task_space_id=7,
            ownership="agentDelegatedToUser",
        )

    async def ego_oauth_browser_status(self, request):
        self.calls.append("ego_browser_status")
        return EgoOAuthBrowserResponse(
            accepted=True,
            state="user_controlled",
            code=self.status_code,
            enrollment_id=request.enrollment_id,
            profile_id="CodexLB-account-target",
            task_space_id=7,
            ownership="agentDelegatedToUser",
        )

    async def ego_oauth_profile_status(self, request):
        self.calls.append("ego_profile_status")
        return EgoOAuthProfileResponse(
            ready=self.profile_ready,
            code="ego_profile_ready" if self.profile_ready else "ego_profile_not_found",
            profile_id="CodexLB-account-target",
        )


class EnrollmentAuth:
    def __init__(self, controls: MemberSwitchControlRepository) -> None:
        self.controls = controls
        self.state = "absent"
        self.owner_state = "absent"
        self.last_preset_id = "target"
        self.prepare_requests = []
        self.snapshot: MemberAuthHandoffResponse | None = None
        self.device_flow_id: str | None = None
        self.pending_advances = 0
        self.advance_calls = 0
        self.prepare_calls = 0
        self.lose_prepare_once = False
        self.lose_advance_once = False
        self.bound_catalog = False
        self.require_bound_catalog = False
        self.raise_observation = False

    def bind_catalog(self, catalog: Catalog) -> None:
        if catalog.catalog_fingerprint != FINGERPRINT:
            raise ControlConflict("auth_catalog_fingerprint_mismatch")
        self.bound_catalog = True

    def validate_identity(self, identity, removed_email=None) -> None:
        if identity.catalog_fingerprint != FINGERPRINT or removed_email is not None:
            raise ControlConflict("auth_catalog_identity_mismatch")

    async def observe_workspace_auth(self, *, workspace_id: str, workspace_account_id: str):
        if self.raise_observation:
            raise RuntimeError("synthetic_auth_observation_failure")
        if self.require_bound_catalog and not self.bound_catalog:
            raise ControlConflict("auth_catalog_not_bound")
        return WorkspaceAuthObservationResponse(
            available=True,
            code="ok",
            workspace_id=workspace_id,
            workspace_account_id=workspace_account_id,
            catalog_fingerprint=FINGERPRINT,
            observed_at=datetime.now(timezone.utc),
            refresh_available=True,
            active_auth_count=1 if self.state == "active" else 0,
            identity_ambiguous=self.state == "ambiguous",
            members=[
                WorkspaceAuthObservationMember(
                    preset_id="target",
                    email="target@example.com",
                    user_id="user-Target",
                    state=self.state,
                    auth_account_id="auth-target" if self.state != "absent" else None,
                ),
                WorkspaceAuthObservationMember(
                    preset_id="owner:workspace-1",
                    email="owner@example.com",
                    user_id="user-Owner",
                    state=self.owner_state,
                    auth_account_id="auth-owner" if self.owner_state != "absent" else None,
                ),
            ],
        )

    async def prepare(self, request, *, managed_run_id=None):
        self.prepare_calls += 1
        self.prepare_requests.append(request)
        self.last_preset_id = request.preset_id
        parent = await self.controls.get(managed_run_id)
        assert parent is not None
        self.snapshot = MemberAuthHandoffResponse(
            handoff_id="handoff-enrollment",
            member_switch_operation_id=request.member_switch_operation_id,
            preset_id=request.preset_id,
            workspace_account_id=request.workspace_account_id,
            target_email=request.target_email,
            target_user_id=request.target_user_id,
            removed_email=request.removed_email,
            state="device_code_issued",
            flow_id="flow-enrollment",
            verification_url="https://auth.example/device",
            user_code="ABCD-EFGH",
            expires_in_seconds=900,
            last_command_id=parent.command_id,
        )
        self.device_flow_id = "flow-enrollment"
        if self.lose_prepare_once:
            self.lose_prepare_once = False
            raise ControlConflict("synthetic_prepare_reply_lost")
        return self.snapshot

    async def advance(self, handoff_id, *, managed_run_id=None):
        assert self.snapshot is not None and handoff_id == self.snapshot.handoff_id
        parent = await self.controls.get(managed_run_id)
        assert parent is not None
        self.advance_calls += 1
        if self.advance_calls <= self.pending_advances:
            self.snapshot = self.snapshot.model_copy(
                update={"state": "oauth_pending", "last_command_id": parent.command_id}
            )
            return self.snapshot
        self.snapshot = self.snapshot.model_copy(update={"state": "completed", "last_command_id": parent.command_id})
        if self.last_preset_id == "owner:workspace-1":
            self.owner_state = "active"
        else:
            self.state = "active"
        if self.lose_advance_once:
            self.lose_advance_once = False
            raise ControlConflict("synthetic_advance_reply_lost")
        return self.snapshot

    async def get_for_operation(self, operation_id):
        if self.snapshot and self.snapshot.member_switch_operation_id == operation_id:
            return self.snapshot
        return None

    async def ensure_device_oauth_available(self, expected_flow_id: str | None = None) -> None:
        if self.device_flow_id is not None and self.device_flow_id != expected_flow_id:
            raise ControlConflict("device_oauth_busy")

    async def reconcile_for_operation(self, operation_id, *, managed_run_id=None):
        return await self.get_for_operation(operation_id)


class EnrollmentPostProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result = AuthEnrollmentPostProbe(
            state="completed",
            account_id="auth-target",
            probe_status_code=429,
            primary_used_percent_after=100.0,
            account_status_after="active",
            usage_refresh_succeeded=True,
        )

    async def probe(self, account_id: str) -> AuthEnrollmentPostProbe:
        self.calls.append(account_id)
        return self.result.model_copy(update={"account_id": account_id})


@pytest_asyncio.fixture
async def enrollment_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'enrollment.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Account.__table__.create)
        await connection.run_sync(MemberSwitchControlRecord.__table__.create)
        await connection.run_sync(MemberSwitchCommandReceipt.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = EnrollmentCompanion()
    auth = EnrollmentAuth(controls)
    service = MemberAuthEnrollmentService(controls, companion, auth)
    yield service, controls, companion, auth
    await engine.dispose()


@pytest_asyncio.fixture
async def enrollment_probe_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'enrollment-probe.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Account.__table__.create)
        await connection.run_sync(MemberSwitchControlRecord.__table__.create)
        await connection.run_sync(MemberSwitchCommandReceipt.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = EnrollmentCompanion()
    auth = EnrollmentAuth(controls)
    post_probe = EnrollmentPostProbe()
    service = MemberAuthEnrollmentService(controls, companion, auth, post_probe)
    yield service, controls, companion, auth, post_probe
    await engine.dispose()


def create_request() -> AuthEnrollmentCreateRequest:
    return AuthEnrollmentCreateRequest(
        enrollment_id=uuid4(),
        workspace_id="workspace-1",
        preset_id="target",
        member_email="target@example.com",
        member_user_id="user-Target",
        catalog_fingerprint=FINGERPRINT,
    )


def owner_request() -> AuthEnrollmentCreateRequest:
    return AuthEnrollmentCreateRequest(
        enrollment_id=uuid4(),
        workspace_id="workspace-1",
        preset_id="owner:workspace-1",
        member_email="owner@example.com",
        member_user_id="user-Owner",
        catalog_fingerprint=FINGERPRINT,
    )


def test_workspace_schema_rejects_owner_oauth_identity_as_member_candidate() -> None:
    with pytest.raises(ValidationError, match="owner_auth_must_not_be_member_candidate"):
        Workspace(
            id="workspace-1",
            workspace_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
            workspace_name="Workspace 1",
            owner_email="owner@example.com",
            owner_auth=OwnerAuthTarget(
                preset_id="owner:workspace-1",
                email="owner@example.com",
                user_id="user-Owner",
            ),
            members=[
                Member(
                    preset_id="target",
                    display_name="bad owner candidate",
                    email="owner@example.com",
                    user_id="user-Owner",
                )
            ],
        )


async def command(service, view, action):
    return await service.command(
        view.id,
        AuthEnrollmentCommandRequest(
            command_id=uuid4(),
            expected_revision=view.revision,
            action=action,
        ),
    )


async def advance_to_auth_confirmed(service: MemberAuthEnrollmentService):
    view = await service.create(create_request())
    view = await command(service, view, "prepare_auth")
    view = await command(service, view, "open_auth_browser")
    return await command(service, view, "advance_auth")


async def test_current_member_oauth_only_flow_never_requests_membership_mutation(enrollment_context):
    service, controls, companion, auth = enrollment_context
    view = await service.create(create_request())
    assert view.phase == "prepared"
    assert view.allowed_actions == ["prepare_auth", "cancel"]
    assert companion.calls == ["catalog", "admission", "catalog", "observe_membership:workspace-1"]

    view = await command(service, view, "prepare_auth")
    assert view.phase == "auth_prepared"
    assert view.user_code == "ABCD-EFGH"
    assert view.verification_url == "https://auth.example/device"
    assert len(auth.prepare_requests) == 1
    request = auth.prepare_requests[0]
    assert request.removed_email is None and request.removed_user_id is None
    assert request.preserve_other_auth is True

    assert view.allowed_actions == ["open_auth_browser"]
    view = await command(service, view, "open_auth_browser")
    assert view.phase == "auth_browser_opened"
    assert view.browser_profile_id == "CodexLB-account-target"
    assert view.browser_task_space_id == 7
    assert view.browser_ownership == "agentDelegatedToUser"
    view = await command(service, view, "advance_auth")
    assert view.phase == "auth_confirmed" and view.auth_state == "completed"
    view = await command(service, view, "finish")
    assert view.phase == "completed"
    assert view.auth_account_id == "auth-target"
    assert await controls.active() is None
    assert all("start" not in call and "participant" not in call for call in companion.calls)


async def test_workspace_owner_uses_same_one_click_oauth_flow_without_membership_mutation(enrollment_probe_context):
    service, controls, companion, auth, post_probe = enrollment_probe_context

    completed = await service.create_and_auto_complete(owner_request())

    assert completed.phase == "completed"
    assert completed.auth_state == "completed"
    assert completed.identity.preset_id == "owner:workspace-1"
    assert completed.identity.target_email == "owner@example.com"
    assert completed.identity.target_user_id == "user-Owner"
    assert completed.auth_account_id == "auth-owner"
    assert post_probe.calls == ["auth-owner"]
    assert len(auth.prepare_requests) == 1
    assert auth.prepare_requests[0].preserve_other_auth is True
    assert auth.prepare_requests[0].removed_email is None
    assert await controls.active() is None
    assert all("start" not in call and "participant" not in call for call in companion.calls)


async def test_workspace_owner_oauth_requires_explicit_companion_capability(enrollment_context):
    service, _, companion, _ = enrollment_context
    companion.owner_oauth_capability = False
    companion.owner_auth_available = False

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await service.create(owner_request())


async def test_auto_resume_rebinds_catalog_before_resolving_auth_account(enrollment_context):
    service, controls, _, auth = enrollment_context
    view = await advance_to_auth_confirmed(service)
    assert view.phase == "auth_confirmed" and view.auth_state == "completed"
    auth.require_bound_catalog = True
    auth.bound_catalog = False  # Simulate a fresh request/service binding.

    completed = await service.auto_complete(view.id)

    assert completed.phase == "completed"
    assert completed.auth_account_id == "auth-target"
    assert auth.bound_catalog is True
    assert await controls.active() is None


async def test_auth_account_resolution_failure_does_not_block_successful_closeout(enrollment_context):
    service, controls, _, auth = enrollment_context
    view = await advance_to_auth_confirmed(service)
    auth.raise_observation = True

    completed = await service.auto_complete(view.id)

    assert completed.phase == "completed" and completed.auth_state == "completed"
    assert completed.auth_account_id is None
    assert completed.post_probe is not None
    assert completed.post_probe.state == "failed"
    assert completed.post_probe.error_code == "oauth_probe_account_unresolved"
    assert await controls.active() is None


async def test_reconcile_lost_finish_persists_exact_auth_account(enrollment_context):
    service, controls, _, auth = enrollment_context
    view = await advance_to_auth_confirmed(service)
    auth.require_bound_catalog = True
    auth.bound_catalog = False
    record = await controls.get(view.id)
    assert record is not None
    finish = AuthEnrollmentCommandRequest(
        command_id=uuid4(), expected_revision=view.revision, action="finish"
    )
    claimed, execute = await controls.claim(
        record,
        str(finish.command_id),
        "finish",
        command_fingerprint("finish", finish.model_dump_json()),
        expected_revision=view.revision,
    )
    assert execute is True and claimed.pending_action == "finish"

    completed = await service.command(
        view.id,
        AuthEnrollmentCommandRequest(
            command_id=uuid4(), expected_revision=claimed.revision, action="reconcile"
        ),
    )

    assert completed.phase == "completed" and completed.auth_state == "completed"
    assert completed.auth_account_id == "auth-target"
    assert await controls.active() is None


async def test_read_only_enrollment_get_never_runs_post_probe(enrollment_probe_context):
    service, controls, _, _, post_probe = enrollment_probe_context
    completed = await service.create_and_auto_complete(create_request())
    assert completed.post_probe is not None
    post_probe.calls.clear()

    read_only_service = MemberAuthEnrollmentService(service.controls, service.companion, service.auth)
    observed = await read_only_service.get(completed.id)

    assert observed is not None and observed.post_probe == completed.post_probe
    assert post_probe.calls == []
    assert await controls.active() is None


class LockObservingPostProbe(EnrollmentPostProbe):
    def __init__(self, controls: MemberSwitchControlRepository) -> None:
        super().__init__()
        self.controls = controls
        self.active_during_probe: list[ControlRecord | None] = []

    async def probe(self, account_id: str) -> AuthEnrollmentPostProbe:
        self.active_during_probe.append(await self.controls.active())
        return await super().probe(account_id)


async def test_terminal_lock_is_released_before_server_post_probe(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'probe-lock-order.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Account.__table__.create)
        await connection.run_sync(MemberSwitchControlRecord.__table__.create)
        await connection.run_sync(MemberSwitchCommandReceipt.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = EnrollmentCompanion()
    auth = EnrollmentAuth(controls)
    post_probe = LockObservingPostProbe(controls)
    service = MemberAuthEnrollmentService(controls, companion, auth, post_probe)
    try:
        completed = await service.create_and_auto_complete(create_request())
        assert completed.phase == "completed"
        assert post_probe.active_during_probe == [None]
        assert await controls.active() is None
    finally:
        await engine.dispose()


class BlockingEnrollmentPostProbe(EnrollmentPostProbe):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def probe(self, account_id: str) -> AuthEnrollmentPostProbe:
        self.calls.append(account_id)
        self.entered.set()
        await self.release.wait()
        return self.result.model_copy(update={"account_id": account_id})


async def test_post_probe_foreign_lease_wait_is_bounded(enrollment_probe_context, monkeypatch):
    service, controls, _, _, post_probe = enrollment_probe_context
    confirmed = await advance_to_auth_confirmed(service)
    completed = await service.command(
        confirmed.id,
        AuthEnrollmentCommandRequest(
            command_id=uuid4(), expected_revision=confirmed.revision, action="finish"
        ),
        run_post_probe=False,
    )
    record = await controls.get(completed.id)
    assert record is not None
    state = service._decode(record).model_copy(
        update={
            "post_probe_claim_id": "foreign-claim",
            "post_probe_claimed_at": datetime.now(timezone.utc),
        }
    )
    await controls.save(record, state.model_dump_json(), complete=True)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_STALE_SECONDS", 0.05)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_POLL_SECONDS", 0.01)

    observed = await asyncio.wait_for(service.auto_complete(completed.id), timeout=1)

    assert observed.phase == "completed"
    assert observed.post_probe is not None
    assert observed.post_probe.state == "failed"
    assert observed.post_probe.error_code == "oauth_probe_outcome_unknown"
    assert post_probe.calls == []
    assert await controls.active() is None


async def test_post_probe_claim_conflict_wait_is_bounded_without_hot_spin(
    enrollment_probe_context, monkeypatch
):
    service, controls, _, _, post_probe = enrollment_probe_context
    confirmed = await advance_to_auth_confirmed(service)
    completed = await service.command(
        confirmed.id,
        AuthEnrollmentCommandRequest(
            command_id=uuid4(), expected_revision=confirmed.revision, action="finish"
        ),
        run_post_probe=False,
    )
    original_save = controls.save
    claim_attempts = 0

    async def conflict_claim(record, payload, **kwargs):
        nonlocal claim_attempts
        candidate = service._decode(record).model_validate_json(payload)
        if candidate.post_probe_claim_id is not None:
            claim_attempts += 1
            raise ControlConflict("revision_conflict")
        return await original_save(record, payload, **kwargs)

    monkeypatch.setattr(controls, "save", conflict_claim)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_POLL_SECONDS", 0.01)
    started = time.monotonic()

    observed = await asyncio.wait_for(service.auto_complete(completed.id), timeout=1)

    elapsed = time.monotonic() - started
    assert observed.phase == "completed" and observed.post_probe is None
    assert post_probe.calls == []
    assert elapsed >= 0.04
    assert claim_attempts <= 8


async def test_concurrent_terminal_requests_share_one_post_probe(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'probe-concurrency.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Account.__table__.create)
        await connection.run_sync(MemberSwitchControlRecord.__table__.create)
        await connection.run_sync(MemberSwitchCommandReceipt.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = EnrollmentCompanion()
    auth = EnrollmentAuth(controls)
    post_probe = BlockingEnrollmentPostProbe()
    service = MemberAuthEnrollmentService(controls, companion, auth, post_probe)
    try:
        confirmed = await advance_to_auth_confirmed(service)
        first = asyncio.create_task(command(service, confirmed, "finish"))
        await asyncio.wait_for(post_probe.entered.wait(), timeout=2)
        second = asyncio.create_task(service.auto_complete(confirmed.id))
        await asyncio.sleep(0.05)
        assert post_probe.calls == ["auth-target"]
        post_probe.release.set()
        first_result, second_result = await asyncio.gather(first, second)

        assert post_probe.calls == ["auth-target"]
        assert first_result.post_probe is not None
        assert second_result.post_probe == first_result.post_probe
        stored = await service.get(confirmed.id)
        assert stored is not None and stored.post_probe == first_result.post_probe
        assert await controls.active() is None
    finally:
        await engine.dispose()


async def test_expired_probe_owner_is_settled_unknown_without_second_probe(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'probe-stale-owner.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Account.__table__.create)
        await connection.run_sync(MemberSwitchControlRecord.__table__.create)
        await connection.run_sync(MemberSwitchCommandReceipt.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    controls = MemberSwitchControlRepository(sessions)
    companion = EnrollmentCompanion()
    auth = EnrollmentAuth(controls)
    post_probe = BlockingEnrollmentPostProbe()
    service = MemberAuthEnrollmentService(controls, companion, auth, post_probe)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_STALE_SECONDS", 0.03)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_WAIT_SECONDS", 0.2)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_POLL_SECONDS", 0.01)
    try:
        confirmed = await advance_to_auth_confirmed(service)
        first = asyncio.create_task(command(service, confirmed, "finish"))
        await asyncio.wait_for(post_probe.entered.wait(), timeout=2)
        await asyncio.sleep(0.05)

        second_result = await service.auto_complete(confirmed.id)

        assert post_probe.calls == ["auth-target"]
        assert second_result.post_probe is not None
        assert second_result.post_probe.error_code == "oauth_probe_outcome_unknown"
        post_probe.release.set()
        first_result = await first
        assert post_probe.calls == ["auth-target"]
        assert first_result.post_probe == second_result.post_probe
    finally:
        post_probe.release.set()
        await engine.dispose()


async def test_server_owned_post_probe_persists_quota_and_is_not_repeated(enrollment_probe_context):
    service, controls, _, _, post_probe = enrollment_probe_context

    completed = await service.create_and_auto_complete(create_request())

    assert completed.phase == "completed" and completed.auth_state == "completed"
    assert completed.auth_account_id == "auth-target"
    assert completed.post_probe is not None
    assert completed.post_probe.state == "completed"
    assert completed.post_probe.probe_status_code == 429
    assert completed.post_probe.primary_used_percent_after == 100.0
    assert post_probe.calls == ["auth-target"]
    assert await controls.active() is None

    retried = await service.auto_complete(completed.id)
    assert retried.post_probe == completed.post_probe
    assert post_probe.calls == ["auth-target"]


async def test_post_probe_persist_failure_retains_attempt_and_stale_settles_without_reprobe(
    enrollment_probe_context, monkeypatch
):
    service, controls, _, _, post_probe = enrollment_probe_context

    async def fail_persist(*_args, **_kwargs):
        raise RuntimeError("synthetic post-probe persistence failure")

    monkeypatch.setattr(service, "_persist_post_probe", fail_persist)
    completed = await service.create_and_auto_complete(create_request())

    assert completed.phase == "completed" and completed.auth_state == "completed"
    assert completed.post_probe is None
    assert post_probe.calls == ["auth-target"]
    record = await controls.get(completed.id)
    assert record is not None
    state = service._decode(record)
    assert state.post_probe_claim_id is not None
    assert state.post_probe_claimed_at is not None
    assert await controls.active() is None

    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._POST_PROBE_STALE_SECONDS", 0)
    recovered = await service.auto_complete(completed.id)

    assert recovered.post_probe is not None
    assert recovered.post_probe.state == "failed"
    assert recovered.post_probe.error_code == "oauth_probe_outcome_unknown"
    assert post_probe.calls == ["auth-target"]
    stored = await controls.get(completed.id)
    assert stored is not None
    settled = service._decode(stored)
    assert settled.post_probe_claim_id is None
    assert settled.post_probe_claimed_at is None


async def test_server_owned_post_probe_failure_keeps_oauth_completed(enrollment_probe_context):
    service, controls, _, _, post_probe = enrollment_probe_context
    post_probe.result = AuthEnrollmentPostProbe(
        state="failed",
        account_id="auth-target",
        error_code="account_probe_refresh_failed",
    )

    completed = await service.create_and_auto_complete(create_request())

    assert completed.phase == "completed" and completed.auth_state == "completed"
    assert completed.post_probe is not None
    assert completed.post_probe.state == "failed"
    assert completed.post_probe.error_code == "account_probe_refresh_failed"
    assert post_probe.calls == ["auth-target"]
    assert await controls.active() is None


async def test_manual_finish_runs_server_owned_post_probe(enrollment_probe_context):
    service, _, _, _, post_probe = enrollment_probe_context
    confirmed = await advance_to_auth_confirmed(service)

    completed = await command(service, confirmed, "finish")

    assert completed.phase == "completed"
    assert completed.post_probe is not None
    assert completed.post_probe.primary_used_percent_after == 100.0
    assert post_probe.calls == ["auth-target"]


async def test_one_click_auto_enrollment_reaches_terminal_and_releases_scope(enrollment_context):
    service, controls, companion, auth = enrollment_context

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "completed"
    assert view.auth_state == "completed"
    assert view.post_probe is not None
    assert view.post_probe.state == "failed"
    assert view.post_probe.error_code == "oauth_probe_adapter_unavailable"
    assert await controls.active() is None
    assert companion.calls.count("open_ego_browser") == 1
    assert auth.advance_calls == 1
    assert len(auth.prepare_requests) == 1
    assert all("start" not in call and "participant" not in call for call in companion.calls)


async def test_one_click_auto_enrollment_polls_oauth_without_reopening_browser(enrollment_context, monkeypatch):
    service, controls, companion, auth = enrollment_context
    auth.pending_advances = 2
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._AUTO_OAUTH_POLL_SECONDS", 0)

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "completed" and view.auth_state == "completed"
    assert companion.calls.count("open_ego_browser") == 1
    assert auth.advance_calls == 3
    assert await controls.active() is None


async def test_one_click_auto_enrollment_stops_for_manual_browser_challenge(enrollment_context):
    service, controls, companion, auth = enrollment_context
    companion.browser_code = "ego_device_auth_user_action_required"

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "auth_browser_opened"
    assert view.last_code == "ego_device_auth_user_action_required"
    assert companion.calls.count("open_ego_browser") == 1
    assert auth.advance_calls == 0
    retained = await controls.active()
    assert retained is not None and retained.id == view.id


async def test_one_click_auto_enrollment_reconciles_unknown_browser_without_replay(enrollment_context):
    service, controls, companion, auth = enrollment_context
    companion.browser_outcome = "unknown"
    companion.status_code = "ego_device_auth_code_submitted"

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "completed" and view.auth_state == "completed"
    assert companion.calls.count("open_ego_browser") == 1
    assert companion.calls.count("ego_browser_status") == 1
    assert auth.advance_calls == 1
    assert await controls.active() is None


async def test_explicit_auto_resume_after_manual_challenge_observes_auth_without_reopening_browser(
    enrollment_context, monkeypatch
):
    service, controls, companion, auth = enrollment_context
    companion.browser_code = "ego_device_auth_user_action_required"
    view = await service.create_and_auto_complete(create_request())
    assert view.phase == "auth_browser_opened"
    assert auth.advance_calls == 0
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._AUTO_OAUTH_POLL_SECONDS", 0)

    resumed = await service.auto_complete(view.id, allow_manual_resume=True)

    assert resumed.phase == "completed" and resumed.auth_state == "completed"
    assert companion.calls.count("open_ego_browser") == 1
    assert auth.advance_calls == 1
    assert await controls.active() is None


async def test_one_click_auto_enrollment_stops_after_bounded_pending_polls(enrollment_context, monkeypatch):
    service, controls, companion, auth = enrollment_context
    auth.pending_advances = 100
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._AUTO_OAUTH_POLL_SECONDS", 0)
    monkeypatch.setattr("app.modules.member_switch.auth_enrollment._AUTO_OAUTH_MAX_ADVANCE_ATTEMPTS", 2)

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "auth_browser_opened"
    assert view.auth_state == "oauth_pending"
    assert auth.advance_calls == 2
    assert companion.calls.count("open_ego_browser") == 1
    assert await controls.active() is not None


async def test_one_click_reconciles_lost_prepare_reply_without_reissuing_device_code(enrollment_context):
    service, controls, companion, auth = enrollment_context
    auth.lose_prepare_once = True

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "completed" and view.auth_state == "completed"
    assert auth.prepare_calls == 1
    assert companion.calls.count("open_ego_browser") == 1
    assert await controls.active() is None


async def test_one_click_reconciles_lost_advance_reply_without_rechecking_browser_effect(enrollment_context):
    service, controls, companion, auth = enrollment_context
    auth.lose_advance_once = True

    view = await service.create_and_auto_complete(create_request())

    assert view.phase == "completed" and view.auth_state == "completed"
    assert auth.advance_calls == 1
    assert companion.calls.count("open_ego_browser") == 1
    assert companion.calls.count("ego_browser_status") == 0
    assert await controls.active() is None


async def test_one_click_auto_enrollment_is_idempotent_after_completion(enrollment_context):
    service, _, companion, auth = enrollment_context
    request = create_request()
    first = await service.create_and_auto_complete(request)
    first_calls = list(companion.calls)
    first_prepare_count = len(auth.prepare_requests)
    first_advance_count = auth.advance_calls

    second = await service.create_and_auto_complete(request)

    assert second.phase == "completed" and second.id == first.id
    assert companion.calls == first_calls
    assert len(auth.prepare_requests) == first_prepare_count
    assert auth.advance_calls == first_advance_count


async def test_enrollment_blocks_other_global_work_until_finished(enrollment_context):
    service, controls, _, _ = enrollment_context
    view = await service.create(create_request())
    with pytest.raises(ControlConflict, match="auth_enrollment_retained"):
        await require_new_work_admission(controls)
    view = await command(service, view, "cancel")
    assert view.phase == "completed"
    await require_new_work_admission(controls)


async def test_enrollment_rejects_member_that_is_not_current(enrollment_context):
    service, controls, companion, _ = enrollment_context
    companion.current_email = "someone-else@example.com"
    companion.current_user_id = "user-SomeoneElse"
    with pytest.raises(ControlConflict, match="oauth_enrollment_member_not_current"):
        await service.create(create_request())
    assert await controls.active() is None


async def test_enrollment_rejects_already_active_or_ambiguous_auth(enrollment_context):
    service, controls, _, auth = enrollment_context
    auth.state = "active"
    with pytest.raises(ControlConflict, match="member_auth_already_active"):
        await service.create(create_request())
    assert await controls.active() is None

    auth.state = "ambiguous"
    with pytest.raises(ControlConflict, match="member_auth_identity_ambiguous"):
        await service.create(create_request())
    assert await controls.active() is None


async def test_companion_admission_blocks_before_membership_observation(enrollment_context):
    service, controls, companion, _ = enrollment_context
    companion.can_start = False
    with pytest.raises(ControlConflict, match="operation_retained"):
        await service.create(create_request())
    assert "observe_membership:workspace-1" not in companion.calls
    assert await controls.active() is None


async def test_existing_device_oauth_blocks_enrollment_before_command_claim(enrollment_context):
    service, controls, _, auth = enrollment_context
    view = await service.create(create_request())
    before = await controls.get(view.id)
    assert before is not None and before.pending_action is None
    auth.device_flow_id = "ordinary-oauth-flow"

    with pytest.raises(ControlConflict, match="device_oauth_busy"):
        await command(service, view, "prepare_auth")

    after = await controls.get(view.id)
    assert after == before
    assert auth.prepare_requests == []


async def test_advance_fails_closed_when_shared_device_slot_is_superseded(enrollment_context):
    service, controls, _, auth = enrollment_context
    view = await service.create(create_request())
    view = await command(service, view, "prepare_auth")
    view = await command(service, view, "open_auth_browser")
    before = await controls.get(view.id)
    assert before is not None and before.pending_action is None

    # An ordinary OAuth start on another lane may supersede the official shared
    # device-flow slot. The managed flow must stop before reading/applying auth.
    auth.device_flow_id = "ordinary-oauth-flow"
    with pytest.raises(ControlConflict, match="device_oauth_busy"):
        await command(service, view, "advance_auth")

    assert await controls.get(view.id) == before
    assert auth.snapshot is not None and auth.snapshot.state == "device_code_issued"


async def test_missing_ego_profile_blocks_before_device_code_start(enrollment_context):
    service, controls, companion, auth = enrollment_context
    view = await service.create(create_request())
    before = await controls.get(view.id)
    companion.profile_ready = False

    with pytest.raises(ControlConflict, match="ego_profile_not_found"):
        await command(service, view, "prepare_auth")

    assert await controls.get(view.id) == before
    assert auth.prepare_requests == []


async def test_advance_revalidates_current_membership_before_oauth_observation(enrollment_context):
    service, controls, companion, auth = enrollment_context
    view = await service.create(create_request())
    view = await command(service, view, "prepare_auth")
    view = await command(service, view, "open_auth_browser")
    before = await controls.get(view.id)
    assert before is not None and before.pending_action is None
    companion.current_email = "someone-else@example.com"
    companion.current_user_id = "user-SomeoneElse"

    with pytest.raises(ControlConflict, match="oauth_enrollment_member_not_current"):
        await command(service, view, "advance_auth")

    after = await controls.get(view.id)
    assert after == before
    assert auth.snapshot is not None and auth.snapshot.state == "device_code_issued"


async def test_known_missing_ego_profile_is_retryable_without_default_browser_fallback(enrollment_context):
    service, controls, companion, auth = enrollment_context
    view = await service.create(create_request())
    view = await command(service, view, "prepare_auth")
    companion.browser_outcome = "missing"

    failed = await command(service, view, "open_auth_browser")

    assert failed.phase == "auth_prepared"
    assert failed.last_code == "ego_profile_not_found"
    assert failed.allowed_actions == ["open_auth_browser"]
    assert auth.snapshot is not None and auth.snapshot.state == "device_code_issued"
    stored = await controls.get(view.id)
    assert stored is not None and stored.pending_action is None


async def test_unknown_ego_open_reconciles_exact_task_without_second_open(enrollment_context):
    service, controls, companion, _ = enrollment_context
    view = await service.create(create_request())
    view = await command(service, view, "prepare_auth")
    companion.browser_outcome = "unknown"

    with pytest.raises(ControlConflict, match="ego_task_space_handoff_failed"):
        await command(service, view, "open_auth_browser")
    retained = await service.get(view.id)
    assert retained is not None and retained.pending_action == "open_auth_browser"
    assert retained.allowed_actions == ["reconcile"]
    assert companion.calls.count("open_ego_browser") == 1

    reconciled = await command(service, retained, "reconcile")
    assert reconciled.phase == "auth_browser_opened"
    assert reconciled.browser_ownership == "agentDelegatedToUser"
    assert companion.calls.count("open_ego_browser") == 1
    assert companion.calls.count("ego_browser_status") == 1


async def test_oauth_enrollment_requires_device_auth_automation_capability(enrollment_context):
    service, _, companion, _ = enrollment_context
    companion.device_auth_automation_capability = False

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await service.create(create_request())

    assert "open_ego_browser" not in companion.calls


async def test_oauth_current_member_validation_requires_owner_ego_capability_before_observation(enrollment_context):
    service, _, companion, _ = enrollment_context
    companion.owner_ego_capability = False

    with pytest.raises(ControlConflict, match="companion_protocol_upgrade_required"):
        await service.create(create_request())

    assert not any(call.startswith("observe_membership:") for call in companion.calls)


async def test_catalog_refresh_decorates_current_member_with_auth_state(enrollment_context):
    _, controls, companion, auth = enrollment_context
    service = MemberSwitchService(controls, companion, auth)

    catalog = await service.refresh_catalog()
    current = catalog.workspaces[0].current_members[0]
    assert current.email == "target@example.com"
    assert current.preset_id == "target"
    assert current.auth_state == "absent"
    assert current.auth_account_id is None
    owner = catalog.workspaces[0].owner_auth
    assert owner is not None
    assert owner.preset_id == "owner:workspace-1"
    assert owner.email == "owner@example.com"
    assert owner.user_id == "user-Owner"
    assert owner.auth_state == "absent"
    assert owner.auth_account_id is None

    auth.state = "active"
    auth.owner_state = "active"
    catalog = await service.refresh_catalog()
    current = catalog.workspaces[0].current_members[0]
    assert current.auth_state == "active"
    assert current.auth_account_id == "auth-target"
    owner = catalog.workspaces[0].owner_auth
    assert owner is not None
    assert owner.auth_state == "active"
    assert owner.auth_account_id == "auth-owner"


async def test_auth_enrollment_auto_route_returns_server_post_probe(enrollment_probe_context):
    service, controls, companion, auth, post_probe = enrollment_probe_context
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ControlConflict, handle_control_conflict)
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_write_access] = lambda: None
    app.dependency_overrides[get_member_switch_controls] = lambda: controls
    app.dependency_overrides[get_member_auth_enrollment_service] = lambda: service
    app.dependency_overrides[get_member_auth_enrollment_command_service] = lambda: service

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        request = create_request()
        completed = await client.post(
            "/api/member-switch-runs/oauth-enrollments/auto",
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()
        assert body["phase"] == "completed"
        assert body["authAccountId"] == "auth-target"
        assert body["postProbe"] == {
            "state": "completed",
            "accountId": "auth-target",
            "probeStatusCode": 429,
            "primaryUsedPercentAfter": 100.0,
            "secondaryUsedPercentAfter": None,
            "accountStatusAfter": "active",
            "usageRefreshSucceeded": True,
            "errorCode": None,
        }
        assert post_probe.calls == ["auth-target"]
        assert auth.advance_calls == 1
        assert companion.calls.count("open_ego_browser") == 1

        retried = await client.post(f"/api/member-switch-runs/oauth-enrollments/{body['id']}/auto")
        assert retried.status_code == 200
        assert retried.json()["postProbe"] == body["postProbe"]
        assert post_probe.calls == ["auth-target"]


async def test_auth_enrollment_auto_routes_complete_and_resume(enrollment_context):
    service, controls, companion, auth = enrollment_context
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ControlConflict, handle_control_conflict)
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_write_access] = lambda: None
    app.dependency_overrides[get_member_switch_controls] = lambda: controls
    app.dependency_overrides[get_member_auth_enrollment_service] = lambda: service
    app.dependency_overrides[get_member_auth_enrollment_command_service] = lambda: service

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        request = create_request()
        completed = await client.post(
            "/api/member-switch-runs/oauth-enrollments/auto",
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()
        assert body["phase"] == "completed" and body["authState"] == "completed"
        assert body["authAccountId"] == "auth-target"
        stored = await service.get(body["id"])
        assert stored is not None and stored.auth_account_id == "auth-target"
        assert await controls.active() is None
        assert companion.calls.count("open_ego_browser") == 1
        assert auth.advance_calls == 1

        resumed = await client.post(f"/api/member-switch-runs/oauth-enrollments/{body['id']}/auto")
        assert resumed.status_code == 200 and resumed.json()["phase"] == "completed"
        assert companion.calls.count("open_ego_browser") == 1
        assert auth.advance_calls == 1


async def test_auth_enrollment_routes_restore_only_through_enrollment_surface(enrollment_context):
    service, controls, companion, _ = enrollment_context
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ControlConflict, handle_control_conflict)
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_write_access] = lambda: None
    app.dependency_overrides[get_member_switch_controls] = lambda: controls
    app.dependency_overrides[get_member_auth_enrollment_service] = lambda: service
    app.dependency_overrides[get_member_auth_enrollment_command_service] = lambda: service

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/member-switch-runs/oauth-enrollments/active")).json() == {"enrollment": None}
        request = create_request()
        created = await client.post(
            "/api/member-switch-runs/oauth-enrollments",
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert created.status_code == 200, created.text
        view = created.json()
        assert view["phase"] == "prepared"
        assert (await client.get("/api/member-switch-runs/active")).json() == {"run": None}

        before = list(companion.calls)
        for _ in range(2):
            observed = await client.get(f"/api/member-switch-runs/oauth-enrollments/{view['id']}")
            assert observed.status_code == 200 and observed.json() == view
        assert companion.calls == before

        command_response = await client.post(
            f"/api/member-switch-runs/oauth-enrollments/{view['id']}/commands",
            json={
                "commandId": str(uuid4()),
                "expectedRevision": view["revision"],
                "action": "prepare_auth",
            },
        )
        assert command_response.status_code == 200, command_response.text
        assert command_response.json()["userCode"] == "ABCD-EFGH"
        assert (await client.get(f"/api/member-switch-runs/oauth-enrollments/{uuid4()}")).status_code == 404
