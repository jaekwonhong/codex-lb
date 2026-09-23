from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from starlette.requests import Request

from app.core.auth.dashboard_access import guest_principal
from app.core.auth.dependencies import validate_dashboard_session
from app.db.models import (
    MemberRotationQuotaOperation,
    MemberRotationWorkspaceControl,
    WorkspaceMemberFinalUsageSnapshot,
    WorkspaceMemberUsageResetInvalidation,
)
from app.db.session import SessionLocal
from app.modules.member_rotation_operator.adapter import (
    NullRotationOperatorSnapshotAdapter,
    OperatorFiveHourObservation,
    OperatorMemberIdentity,
    RotationOperatorSnapshot,
    set_rotation_operator_snapshot_adapter,
)
from app.modules.member_switch.rotation_foundation import RotationFoundationReadModel, RotationFoundationState

pytestmark = pytest.mark.integration

WORKSPACE_ID = "cdp-1"
WORKSPACE_ACCOUNT_ID = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"


class _SnapshotAdapter:
    async def snapshot(self, *, workspace_id: str, workspace_account_id: str):
        if workspace_id != WORKSPACE_ID:
            return None
        return RotationOperatorSnapshot(
            workspace_id=workspace_id,
            workspace_account_id=workspace_account_id,
            foundation=RotationFoundationReadModel(
                state=RotationFoundationState.RESET_RECONCILIATION_PENDING,
                admission_ready=False,
                attention_required=True,
                weekly_state="exhausted",
                weekly_reason=None,
                reset_status="reconciliation_pending",
                quota_code=None,
                count_24h=2,
                count_168h=5,
            ),
            current_member=OperatorMemberIdentity(
                preset_id="cdp-1-allnz-jk",
                email="allnz.jk@gmail.com",
                user_id="user-F35N1VBxC5M3BC4LQHhamB8a",
            ),
            five_hour=OperatorFiveHourObservation(
                state="observed",
                used_percent=81.25,
                reset_at=1_800_000_000,
                observed_at=datetime(2026, 9, 13, 11, 0, tzinfo=timezone.utc),
            ),
            # Deliberately conflicts with G1. P6 must keep the authoritative
            # foundation reconciliation state instead of showing recovery.
            reset_state="usage_recovered",
            controller_status="needs_attention",
            controller_reason="reset_reconciliation_pending",
            # This is the owner of cdp-1 and must be filtered even if an adapter reports it.
            next_candidate=OperatorMemberIdentity(
                preset_id="owner:cdp-1",
                email="jaekwonhong14@gmail.com",
                user_id="user-owner",
            ),
            blocker_codes=("reset_reconciliation_pending",),
            invitation_issued=True,
            membership_confirmed=False,
            companion_status="provenance_mismatch",
            removed_at_by_membership_epoch={
                "epoch-1": datetime(2026, 9, 12, 9, 30, tzinfo=timezone.utc),
            },
        )


@pytest.fixture(autouse=True)
def _reset_snapshot_adapter():
    set_rotation_operator_snapshot_adapter(NullRotationOperatorSnapshotAdapter())
    yield
    set_rotation_operator_snapshot_adapter(NullRotationOperatorSnapshotAdapter())


@pytest.mark.asyncio
async def test_operator_read_is_default_off_and_does_not_persist_control(async_client):
    response = await async_client.get("/api/member-rotation/operator")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["schemaVersion"] == 1
    assert payload["workspaces"]
    assert all(workspace["automaticRotationEnabled"] is False for workspace in payload["workspaces"])
    assert all(workspace["controlVersion"] == 0 for workspace in payload["workspaces"])

    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(MemberRotationWorkspaceControl))
    assert count == 0


@pytest.mark.asyncio
async def test_explicit_intent_write_is_cas_scoped_and_status_reads_only_the_saved_intent(async_client):
    saved = await async_client.put(
        f"/api/member-rotation/operator/workspaces/{WORKSPACE_ID}/intent",
        json={"enabled": True, "expectedVersion": 0},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "workspaceId": WORKSPACE_ID,
        "workspaceAccountId": WORKSPACE_ACCOUNT_ID,
        "enabled": True,
        "version": 1,
    }

    stale = await async_client.put(
        f"/api/member-rotation/operator/workspaces/{WORKSPACE_ID}/intent",
        json={"enabled": False, "expectedVersion": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "rotation_intent_conflict"

    listed = await async_client.get("/api/member-rotation/operator")
    workspace = next(item for item in listed.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)
    assert workspace["automaticRotationEnabled"] is True
    assert workspace["controlVersion"] == 1
    # P6 has no effect command endpoint; enabling intent alone reports an integration boundary.
    assert workspace["controller"]["status"] == "integration_pending"
    assert "controller_snapshot_unavailable" in workspace["blockerCodes"]


@pytest.mark.asyncio
async def test_sequential_intent_updates_return_committed_values_and_versions(async_client):
    endpoint = f"/api/member-rotation/operator/workspaces/{WORKSPACE_ID}/intent"
    returned_version = 0
    for enabled in (True, False, True):
        saved = await async_client.put(endpoint, json={"enabled": enabled, "expectedVersion": returned_version})
        assert saved.status_code == 200
        assert saved.json() == {
            "workspaceId": WORKSPACE_ID,
            "workspaceAccountId": WORKSPACE_ACCOUNT_ID,
            "enabled": enabled,
            "version": returned_version + 1,
        }
        returned_version = saved.json()["version"]
        listed = await async_client.get("/api/member-rotation/operator")
        assert listed.status_code == 200
        workspace = next(item for item in listed.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)
        assert workspace["automaticRotationEnabled"] is enabled
        assert workspace["controlVersion"] == returned_version

    stale = await async_client.put(endpoint, json={"enabled": False, "expectedVersion": returned_version - 1})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "rotation_intent_conflict"


@pytest.mark.asyncio
async def test_intent_update_keeps_stored_workspace_identity_binding(async_client):
    async with SessionLocal() as session:
        session.add(
            MemberRotationWorkspaceControl(
                workspace_id=WORKSPACE_ID,
                workspace_account_id="previous-workspace-account",
                automatic_rotation_enabled=False,
                version=1,
            )
        )
        await session.commit()

    response = await async_client.put(
        f"/api/member-rotation/operator/workspaces/{WORKSPACE_ID}/intent",
        json={"enabled": True, "expectedVersion": 1},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "rotation_intent_conflict"
    async with SessionLocal() as session:
        row = await session.get(MemberRotationWorkspaceControl, WORKSPACE_ID)
        assert row is not None
        assert row.workspace_account_id == "previous-workspace-account"
        assert row.automatic_rotation_enabled is False
        assert row.version == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("with_foundation", [False, True], ids=["default-off", "non-null-foundation"])
async def test_actual_operator_response_parses_in_typescript_client(async_client, with_foundation):
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    node = shutil.which("node")
    if node is None or not (frontend / "node_modules/typescript/package.json").is_file():
        pytest.skip("Operator wire contract requires Node and the installed frontend dependencies")
    if with_foundation:
        set_rotation_operator_snapshot_adapter(_SnapshotAdapter())
    response = await async_client.get("/api/member-rotation/operator")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    workspace = next(item for item in response.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)
    assert workspace["automaticRotationEnabled"] is False
    if with_foundation:
        assert workspace["foundation"]["count24H"] == 2
        assert workspace["foundation"]["count168H"] == 5
    else:
        assert workspace["foundation"] is None

    # Pass unmodified ASGI response bytes through the product TS schema and API
    # client, rather than maintaining a separate hand-written wire fixture.
    checked = subprocess.run(
        [node, str(frontend / "src/features/member-rotation/operator-wire-contract.cjs")],
        input=response.text,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.asyncio
async def test_operator_preserves_g1_weekly_classification_and_hides_owner_candidate(async_client):
    set_rotation_operator_snapshot_adapter(_SnapshotAdapter())
    response = await async_client.get("/api/member-rotation/operator")
    assert response.status_code == 200
    workspace = next(item for item in response.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)

    assert workspace["weeklyUsage"] == {"state": "exhausted", "reason": None}
    assert workspace["foundation"]["state"] == "reset_reconciliation_pending"
    assert workspace["resetCredit"]["state"] == "reconciliation_pending"
    assert workspace["controller"]["status"] == "needs_attention"
    assert workspace["fiveHourUsage"]["usedPercent"] == 81.25
    assert workspace["nextCandidate"] is None
    assert "invalid_next_candidate" in workspace["blockerCodes"]
    assert "companion_provenance_mismatch" in workspace["blockerCodes"]
    assert workspace["controller"]["invitationIssued"] is True
    assert workspace["controller"]["membershipConfirmed"] is False


@pytest.mark.asyncio
async def test_operator_history_keeps_original_reset_and_marks_effective_reset_invalidated(async_client):
    set_rotation_operator_snapshot_adapter(_SnapshotAdapter())
    retained_at = datetime(2026, 9, 12, 9, 29, 58)
    observed_at = datetime(2026, 9, 12, 9, 29, 50)
    invalidation = WorkspaceMemberUsageResetInvalidation(
        id="invalidation-1",
        cutoff_at=datetime(2026, 9, 12, 10, 0),
        affected_count=2,
    )
    rows = [
        WorkspaceMemberFinalUsageSnapshot(
            id="snapshot-5h",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_id="account-removed",
            preset_id="removed-preset",
            email="removed@example.com",
            user_id="user-removed",
            membership_epoch="epoch-1",
            logical_window="5h",
            source_window="primary",
            used_percent=98.5,
            reset_at=1_800_000_000,
            window_minutes=300,
            observed_at=observed_at,
            fetch_provenance="stored",
            fetch_succeeded=True,
            usage_written=True,
            retained_at=retained_at,
            reset_invalidation_id="invalidation-1",
        ),
        WorkspaceMemberFinalUsageSnapshot(
            id="snapshot-weekly",
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_id="account-removed",
            preset_id="removed-preset",
            email="removed@example.com",
            user_id="user-removed",
            membership_epoch="epoch-1",
            logical_window="weekly",
            source_window="secondary",
            used_percent=100.0,
            reset_at=1_800_500_000,
            window_minutes=10_080,
            observed_at=observed_at,
            fetch_provenance="stored",
            fetch_succeeded=True,
            usage_written=True,
            retained_at=retained_at,
            reset_invalidation_id="invalidation-1",
        ),
    ]
    async with SessionLocal() as session:
        session.add(invalidation)
        await session.flush()
        session.add_all(rows)
        await session.commit()

    response = await async_client.get("/api/member-rotation/operator")
    workspace = next(item for item in response.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)
    history = workspace["history"][0]
    assert history["removedAt"].startswith("2026-09-12T09:30:00")
    assert history["fiveHour"]["usedPercent"] == 98.5
    assert history["fiveHour"]["originalResetAt"] == 1_800_000_000
    assert history["fiveHour"]["effectiveResetAt"] is None
    assert history["fiveHour"]["resetScheduleInvalidated"] is True
    assert history["weekly"]["usedPercent"] == 100.0
    assert history["weekly"]["originalResetAt"] == 1_800_500_000
    assert history["weekly"]["effectiveResetAt"] is None


@pytest.mark.asyncio
async def test_unknown_effects_remain_attention_and_are_not_replayed(async_client):
    now = datetime(2026, 9, 13, 11, 0)
    async with SessionLocal() as session:
        session.add(
            MemberRotationQuotaOperation(
                operation_id="operation-unknown",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                rotation_event_id="rotation-event-unknown",
                requested_at=now,
                initial_admission_code="admitted",
                reserved_at=now,
                remove_requested_at=now,
                remove_effect="unknown",
                invite_requested_at=now,
                invite_effect="unknown",
                # G1/P3 deliberately fail closed for legacy/corrupt rows that
                # carry completion while an external effect remains unknown.
                completed_at=now,
            )
        )
        await session.commit()

    response = await async_client.get("/api/member-rotation/operator")
    workspace = next(item for item in response.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)
    assert "unknown_remove_effect" in workspace["blockerCodes"]
    assert "unknown_invite_effect" in workspace["blockerCodes"]
    assert workspace["controller"]["removeEffect"] == "unknown"
    assert workspace["controller"]["inviteEffect"] == "unknown"

    async with SessionLocal() as session:
        row = await session.get(MemberRotationQuotaOperation, "operation-unknown")
        assert row is not None
        assert row.remove_effect == "unknown"
        assert row.invite_effect == "unknown"
        assert row.remove_requested_at == now
        assert row.invite_requested_at == now


@pytest.mark.asyncio
async def test_guest_cannot_observe_or_change_member_rotation_operator_state(app_instance, async_client):
    async def as_guest(request: Request):
        principal = guest_principal()
        request.state.dashboard_principal = principal
        return principal

    app_instance.dependency_overrides[validate_dashboard_session] = as_guest
    try:
        readable = await async_client.get("/api/member-rotation/operator")
        assert readable.status_code == 403
        assert readable.json()["error"]["code"] == "permission_required"

        blocked = await async_client.put(
            f"/api/member-rotation/operator/workspaces/{WORKSPACE_ID}/intent",
            json={"enabled": True, "expectedVersion": 0},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "permission_required"
    finally:
        app_instance.dependency_overrides.pop(validate_dashboard_session, None)
