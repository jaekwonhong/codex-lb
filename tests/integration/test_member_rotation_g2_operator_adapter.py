from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models import (
    MemberRotationQuotaOperation,
    MemberSwitchControlRecord,
    WorkspaceMemberFinalUsageSnapshot,
)
from app.db.session import SessionLocal
from app.modules.member_rotation_operator.adapter import (
    DurableRotationOperatorSnapshotAdapter,
    NullRotationOperatorSnapshotAdapter,
    set_rotation_operator_snapshot_adapter,
)
from app.modules.member_switch.schemas import (
    P4_TYPED_TELEMETRY_BINARY_SHA256,
    P4_TYPED_TELEMETRY_CONTRACT,
    P4_TYPED_TELEMETRY_OPS_COMMIT,
    P4_TYPED_TELEMETRY_VERSION,
    CompanionTypedTelemetryProvenance,
    Identity,
    RotationControllerState,
)

pytestmark = pytest.mark.integration

WORKSPACE_ID = "cdp-1"
WORKSPACE_ACCOUNT_ID = "4865cea4-fb0b-41f3-917c-b226b2acdfb0"
OUTGOING_PRESET = "cdp-1-allnz-jk"
OUTGOING_EMAIL = "allnz.jk@gmail.com"
OUTGOING_USER = "user-F35N1VBxC5M3BC4LQHhamB8a"
INCOMING_PRESET = "cdp-1-thinklet03"
INCOMING_EMAIL = "thinklet03@gmail.com"
INCOMING_USER = "user-9I446YqZTQ9z0Wq6zCzvJ0Sl"
NOW = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)


def _controller_state() -> RotationControllerState:
    return RotationControllerState(
        id="rotation-controller:g2-read-model",
        evaluation_id="g2-read-model",
        workspace_id=WORKSPACE_ID,
        workspace_account_id=WORKSPACE_ACCOUNT_ID,
        outgoing_account_id="account-outgoing",
        outgoing_preset_id=OUTGOING_PRESET,
        outgoing_email=OUTGOING_EMAIL,
        outgoing_user_id=OUTGOING_USER,
        incoming=Identity(
            workspace_id=WORKSPACE_ID,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
            preset_id=INCOMING_PRESET,
            target_email=INCOMING_EMAIL,
            target_user_id=INCOMING_USER,
            catalog_fingerprint="a" * 64,
        ),
        foundation_state="reset_reconciliation_pending",
        foundation_evidence_ref="fetch-g2",
        foundation_admission_ready=False,
        foundation_attention_required=True,
        foundation_weekly_state="exhausted",
        foundation_weekly_reason="weekly_exhausted",
        reset_status="reconciliation_pending",
        foundation_quota_code=None,
        foundation_count_24h=2,
        foundation_count_168h=5,
        quota_operation_id="quota-g2-read-model",
        membership_epoch="epoch-g2-read-model",
        p4_provenance=CompanionTypedTelemetryProvenance(
            contract=P4_TYPED_TELEMETRY_CONTRACT,
            version=P4_TYPED_TELEMETRY_VERSION,
            binary_sha256=P4_TYPED_TELEMETRY_BINARY_SHA256,
            ops_commit=P4_TYPED_TELEMETRY_OPS_COMMIT,
        ),
        p4_provenance_verified=True,
        snapshot_committed=True,
        final_snapshot_ids=["g2-final-5h", "g2-final-weekly"],
        member_switch_run_id="rotation-run:g2-read-model",
        start_command_id="start-g2-read-model",
        remove_state="not_attempted",
        invite_state="not_attempted",
        phase="needs_attention",
        last_code="reset_reconciliation_pending",
        terminal_reason="reset_reconciliation_pending",
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_g2_operator_uses_durable_p5_snapshot_without_authorizing_effects(async_client) -> None:
    state = _controller_state()
    async with SessionLocal() as session:
        session.add(
            MemberSwitchControlRecord(
                id=state.id,
                kind="rotation",
                active_scope=None,
                revision=1,
                payload=state.model_dump_json(),
                pending_action=None,
                command_id=None,
                command_hash=None,
            )
        )
        session.add(
            MemberRotationQuotaOperation(
                operation_id="quota-g2-read-model",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                requested_at=NOW.replace(tzinfo=None),
                initial_admission_code="admitted",
                reserved_at=NOW.replace(tzinfo=None),
            )
        )
        for snapshot_id, window, used, reset_at, minutes in (
            ("g2-final-5h", "5h", 81.25, 1_800_000_000, 300),
            ("g2-final-weekly", "weekly", 100.0, 1_800_500_000, 10_080),
        ):
            session.add(
                WorkspaceMemberFinalUsageSnapshot(
                    id=snapshot_id,
                    workspace_id=WORKSPACE_ID,
                    workspace_account_id=WORKSPACE_ACCOUNT_ID,
                    account_id="account-outgoing",
                    preset_id=OUTGOING_PRESET,
                    email=OUTGOING_EMAIL,
                    user_id=OUTGOING_USER,
                    membership_epoch="epoch-g2-read-model",
                    logical_window=window,
                    source_window="primary" if window == "5h" else "secondary",
                    used_percent=used,
                    reset_at=reset_at,
                    window_minutes=minutes,
                    observed_at=NOW.replace(tzinfo=None),
                    fetch_provenance="fetch-g2",
                    fetch_succeeded=True,
                    usage_written=True,
                    retained_at=NOW.replace(tzinfo=None),
                )
            )
        await session.commit()

    set_rotation_operator_snapshot_adapter(DurableRotationOperatorSnapshotAdapter())
    try:
        response = await async_client.get("/api/member-rotation/operator")
    finally:
        set_rotation_operator_snapshot_adapter(NullRotationOperatorSnapshotAdapter())

    assert response.status_code == 200
    workspace = next(item for item in response.json()["workspaces"] if item["workspaceId"] == WORKSPACE_ID)
    assert workspace["automaticRotationEnabled"] is False
    assert workspace["foundation"]["state"] == "reset_reconciliation_pending"
    assert workspace["weeklyUsage"] == {"state": "exhausted", "reason": "weekly_exhausted"}
    assert workspace["resetCredit"]["state"] == "reconciliation_pending"
    assert workspace["fiveHourUsage"]["usedPercent"] == 81.25
    assert workspace["currentMember"]["presetId"] == OUTGOING_PRESET
    assert workspace["nextCandidate"]["presetId"] == INCOMING_PRESET
    assert workspace["controller"]["status"] == "needs_attention"
    assert workspace["controller"]["companionStatus"] == "qualified"
    assert "reset_reconciliation_pending" in workspace["blockerCodes"]
