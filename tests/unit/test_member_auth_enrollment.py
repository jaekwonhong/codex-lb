from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.auth.dependencies import require_dashboard_write_access, validate_dashboard_session
from app.db.models import Account, MemberSwitchCommandReceipt, MemberSwitchControlRecord
from app.dependencies import (
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
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.schemas import (
    AuthEnrollmentCommandRequest,
    AuthEnrollmentCreateRequest,
    Catalog,
    CompanionAdmission,
    EgoOAuthBrowserResponse,
    EgoOAuthProfileResponse,
    Member,
    MembershipObservation,
    MembershipObservationMember,
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
            + (["ego_lite_owner_membership_observation_v1"] if self.owner_ego_capability else []),
            workspaces=[
                Workspace(
                    id="workspace-1",
                    workspace_account_id=WORKSPACE_ID,
                    workspace_name="Workspace 1",
                    owner_email="owner@example.com",
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
            code="ego_task_space_handed_off",
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
            code="ego_task_space_user_controlled",
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
        self.prepare_requests = []
        self.snapshot: MemberAuthHandoffResponse | None = None
        self.device_busy = False

    def bind_catalog(self, catalog: Catalog) -> None:
        if catalog.catalog_fingerprint != FINGERPRINT:
            raise ControlConflict("auth_catalog_fingerprint_mismatch")

    def validate_identity(self, identity, removed_email=None) -> None:
        if identity.catalog_fingerprint != FINGERPRINT or removed_email is not None:
            raise ControlConflict("auth_catalog_identity_mismatch")

    async def observe_workspace_auth(self, *, workspace_id: str, workspace_account_id: str):
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
                )
            ],
        )

    async def prepare(self, request, *, managed_run_id=None):
        self.prepare_requests.append(request)
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
        return self.snapshot

    async def advance(self, handoff_id, *, managed_run_id=None):
        assert self.snapshot is not None and handoff_id == self.snapshot.handoff_id
        parent = await self.controls.get(managed_run_id)
        assert parent is not None
        self.snapshot = self.snapshot.model_copy(update={"state": "completed", "last_command_id": parent.command_id})
        self.state = "active"
        return self.snapshot

    async def get_for_operation(self, operation_id):
        if self.snapshot and self.snapshot.member_switch_operation_id == operation_id:
            return self.snapshot
        return None

    async def ensure_device_oauth_available(self, expected_flow_id: str | None = None) -> None:
        if self.device_busy and expected_flow_id != "flow-enrollment":
            raise ControlConflict("device_oauth_busy")

    async def reconcile_for_operation(self, operation_id, *, managed_run_id=None):
        return await self.get_for_operation(operation_id)


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


def create_request() -> AuthEnrollmentCreateRequest:
    return AuthEnrollmentCreateRequest(
        enrollment_id=uuid4(),
        workspace_id="workspace-1",
        preset_id="target",
        member_email="target@example.com",
        member_user_id="user-Target",
        catalog_fingerprint=FINGERPRINT,
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
    assert await controls.active() is None
    assert all("start" not in call and "participant" not in call for call in companion.calls)


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
    auth.device_busy = True

    with pytest.raises(ControlConflict, match="device_oauth_busy"):
        await command(service, view, "prepare_auth")

    after = await controls.get(view.id)
    assert after == before
    assert auth.prepare_requests == []


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

    auth.state = "active"
    catalog = await service.refresh_catalog()
    current = catalog.workspaces[0].current_members[0]
    assert current.auth_state == "active"
    assert current.auth_account_id == "auth-target"


async def test_auth_enrollment_routes_restore_only_through_enrollment_surface(enrollment_context):
    service, controls, companion, _ = enrollment_context
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ControlConflict, handle_control_conflict)
    app.dependency_overrides[validate_dashboard_session] = lambda: None
    app.dependency_overrides[require_dashboard_write_access] = lambda: None
    app.dependency_overrides[get_member_switch_controls] = lambda: controls
    app.dependency_overrides[get_member_auth_enrollment_service] = lambda: service

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
