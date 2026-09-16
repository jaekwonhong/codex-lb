from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.usage.weekly_observation import (
    ClassifiedUsageWindowObservation,
    RotationUsageObservation,
    UsageAccountIdentity,
    UsageFetchProvenance,
)
from app.db.models import Base, MemberRotationQuotaOperation
from app.modules.member_auth_handoff.rotation_events import RotationQuotaDecision, RotationQuotaRepository
from app.modules.member_switch.rotation_foundation import (
    RotationEvaluationIdentity,
    RotationFoundationState,
    RotationQuotaReservationEvidence,
    RotationResetEvidence,
    RotationWeeklyEvidence,
    bind_rotation_reset_resolution,
    bind_rotation_weekly_evidence,
    evaluate_rotation_foundation,
)
from app.modules.rate_limit_reset_credits.rotation_resolution import (
    RotationResetCreditResolution,
    RotationResetCreditResolutionStatus,
)
from scripts.member_rotation_release_qualification import (
    CONCURRENCY_CASES,
    FAILURE_BOUNDARY_CASES,
    G1_SHA,
    LEGACY_DASHBOARD_CREDENTIAL_COLUMNS,
    MEMBER_ROTATION_EXTENSION_CONTRACT,
    P4_BINARY_SHA256,
    P4_CAPTURE_CASES,
    P4_CONTRACT,
    P4_OWNING_OPS_COMMIT,
    P4_PATCH_SHA256,
    P4_PATCH_UNCOMPRESSED_SHA256,
    P4_RECONSTRUCTION_BASELINE,
    P4_REPLAY_TOUCHED_TREE_SHA256,
    P4_TYPED_VALUE_CASES,
    P4_VERSION,
    PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
    PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
    ROLLBACK_EXTENSION_TABLES,
    ROLLBACK_STATE_KEYS,
    DurableEffectReceipt,
    EffectKind,
    ExternalEffects,
    QualificationError,
    ScenarioResult,
    TelemetryObservation,
    authorize_canary_effect,
    qualify_effect_gate,
    qualify_p4_telemetry_matrix,
    qualify_restart_no_replay,
    qualify_retention_before_remove,
    qualify_scenario_matrix,
    verify_canary_events,
    verify_preflight,
    verify_rollback_state,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
WORKSPACE_ID = "workspace-1"
WORKSPACE_ACCOUNT_ID = "workspace-account-1"
STABLE_SHA256 = "c" * 64
BETA_SHA256 = "d" * 64
ROLLBACK_SHA256 = "e" * 64
ROLLBACK_STABLE_SHA256 = "1" * 64
ROLLBACK_BETA_SHA256 = "2" * 64
ROLLBACK_STABLE_SOURCE_SHA = "3" * 40
ROLLBACK_BETA_SOURCE_SHA = "4" * 40
ROLLBACK_DATABASE_CONTAINER_ID = "5" * 64
ROLLBACK_DATABASE_SYSTEM_IDENTIFIER = "8684501606386458669"
ROLLBACK_DATABASE_SNAPSHOT = "6" * 64
ROLLBACK_CREDENTIAL_FINGERPRINT = "a" * 64
ROLLBACK_STABLE_CONTAINER_ID = "7" * 64
ROLLBACK_BETA_CONTAINER_ID = "e" * 64
POSTGRES_CONTAINER_ID = "f" * 64
POSTGRES_SYSTEM_IDENTIFIER = "7684501606386458669"
POSTGRES_SNAPSHOT = "9" * 64
EXTENSION_SCHEMA_SHA256 = "8" * 64
STABLE_ROLE = "stable-v1.25.0-beta.7-official"
BETA_ROLE = "beta-v1.25.0-beta.7-q2-usage-member-rotation-default-off-dgx-encrypted-reasoning"
MEMBER = UsageAccountIdentity(
    account_id="local-seat-a",
    workspace_account_id=WORKSPACE_ACCOUNT_ID,
    user_id="user-a",
    email="member-a@example.com",
)
EVALUATION = RotationEvaluationIdentity(
    evaluation_id="evaluation-a",
    workspace_id=WORKSPACE_ID,
    member=MEMBER,
    redeem_request_id="reset-request-a",
)
MATRIX_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "member_switch" / "p7_qualification_matrix.json"
P4_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "member_switch" / "p7_p4_telemetry.json"


def _extension_table_fingerprints() -> dict[str, dict[str, int | str]]:
    return {
        table: {"count": index, "sha256": hashlib.sha256(table.encode()).hexdigest()}
        for index, table in enumerate(ROLLBACK_EXTENSION_TABLES, start=1)
    }


def _receipt(
    *,
    weekly_used: float | None = 100.0,
    observed_at: datetime = NOW,
    weekly_reset_at: int | None = None,
) -> RotationUsageObservation:
    return RotationUsageObservation(
        fetch_succeeded=True,
        usage_written=False,
        provenance=UsageFetchProvenance(
            fetch_id=f"fetch-{int(observed_at.timestamp())}",
            identity=MEMBER,
            requested_workspace_account_id=WORKSPACE_ACCOUNT_ID,
            account_workspace_id="metadata-workspace-a",
            payload_workspace_id="metadata-workspace-a",
            credential_source="stored",
            started_at=observed_at - timedelta(seconds=1),
            observed_at=observed_at,
        ),
        five_hour_window=ClassifiedUsageWindowObservation(
            source_slot="primary",
            raw_used_percent=45.0,
            window_minutes=300,
            limit_window_seconds=18_000,
            reset_at=int((NOW + timedelta(hours=1)).timestamp()),
        ),
        weekly_window=ClassifiedUsageWindowObservation(
            source_slot="secondary",
            raw_used_percent=weekly_used,
            window_minutes=10_080,
            limit_window_seconds=604_800,
            reset_at=weekly_reset_at or int((NOW + timedelta(days=1)).timestamp()),
        ),
    )


def _weekly(
    *,
    weekly_used: float | None = 100.0,
    observed_at: datetime = NOW,
) -> RotationWeeklyEvidence:
    return bind_rotation_weekly_evidence(
        _receipt(weekly_used=weekly_used, observed_at=observed_at),
        EVALUATION,
    )


def _reset(status: RotationResetCreditResolutionStatus) -> RotationResetEvidence:
    return bind_rotation_reset_resolution(
        EVALUATION,
        RotationResetCreditResolution(
            status=status,
            redeem_request_id=EVALUATION.redeem_request_id,
            account_id=MEMBER.account_id,
            workspace_account_id=WORKSPACE_ACCOUNT_ID,
        ),
    )


def test_frozen_matrix_matches_release_qualification_contract() -> None:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    assert matrix["g1_sha"] == G1_SHA
    assert tuple(matrix["failure_boundary_cases"]) == FAILURE_BOUNDARY_CASES
    assert tuple(matrix["concurrency_cases"]) == CONCURRENCY_CASES
    assert tuple(matrix["p4"]["typed_value_cases"]) == P4_TYPED_VALUE_CASES
    assert tuple(matrix["p4"]["capture_cases"]) == P4_CAPTURE_CASES
    assert tuple(matrix["rollback_state_keys"]) == ROLLBACK_STATE_KEYS
    assert tuple(matrix["rollback_extension_tables"]) == ROLLBACK_EXTENSION_TABLES
    assert matrix["p4"]["artifact_owning_ops_commit"] == P4_OWNING_OPS_COMMIT
    assert matrix["p4"]["reconstructed_source_baseline"] == P4_RECONSTRUCTION_BASELINE
    assert matrix["p4"]["candidate_version"] == P4_VERSION
    assert matrix["p4"]["candidate_binary_sha256"] == P4_BINARY_SHA256
    assert matrix["p4"]["patch_sha256"] == P4_PATCH_SHA256
    assert matrix["p4"]["patch_uncompressed_sha256"] == P4_PATCH_UNCOMPRESSED_SHA256
    assert matrix["p4"]["replay_touched_tree_sha256"] == P4_REPLAY_TOUCHED_TREE_SHA256
    assert matrix["p4"]["billed_seat_delta_is_quota_input"] is False
    assert matrix["p4"]["undocumented_server_threshold_can_relax_local_policy"] is False
    assert matrix["no_replay_contract"] == {
        "durable_receipt_identity_required": True,
        "restart_must_reconstruct_same_receipt": True,
        "authoritative_reconciliation_must_return_same_receipt": True,
    }
    assert matrix["canary"]["pre_effect_authorization_required"] is True
    assert matrix["canary"]["remove_reconciliation_required_before_invite"] is True
    assert P4_OWNING_OPS_COMMIT != P4_RECONSTRUCTION_BASELINE

    root = Path(__file__).resolve().parents[2]
    for relative in matrix["qualification_suite_files"]:
        assert (root / relative).is_file(), f"qualification suite file is missing: {relative}"


def test_g1_failure_boundary_matrix_remains_effect_free() -> None:
    effects = ExternalEffects()
    zero_effect_results: dict[str, ScenarioResult] = {}

    unknown = evaluate_rotation_foundation(
        _weekly(weekly_used=None),
        current_member=MEMBER,
        now=NOW,
    )
    assert unknown.state is RotationFoundationState.USAGE_UNKNOWN
    zero_effect_results["unknown_weekly"] = ScenarioResult(effects, effects, "unknown_weekly-window")

    stale = evaluate_rotation_foundation(
        _weekly(observed_at=NOW - timedelta(minutes=20)),
        current_member=MEMBER,
        now=NOW,
    )
    assert stale.state is RotationFoundationState.USAGE_UNKNOWN and stale.weekly_reason == "stale"
    zero_effect_results["stale_weekly"] = ScenarioResult(effects, effects, "stale_weekly-window")

    reset_required = evaluate_rotation_foundation(
        _weekly(),
        current_member=MEMBER,
        now=NOW,
    )
    assert reset_required.state is RotationFoundationState.RESET_REQUIRED
    zero_effect_results["reset_required"] = ScenarioResult(effects, effects, "reset_required-window")

    status_cases = {
        "reset_pending": (
            RotationResetCreditResolutionStatus.RECONCILIATION_PENDING,
            RotationFoundationState.RESET_RECONCILIATION_PENDING,
        ),
        "reset_unavailable": (
            RotationResetCreditResolutionStatus.UNAVAILABLE,
            RotationFoundationState.RESET_UNAVAILABLE,
        ),
        "reset_recovered": (
            RotationResetCreditResolutionStatus.USAGE_RECOVERED,
            RotationFoundationState.RESET_RECOVERED,
        ),
    }
    for case, (status, expected_state) in status_cases.items():
        decision = evaluate_rotation_foundation(
            _weekly(),
            current_member=MEMBER,
            now=NOW,
            reset=_reset(status),
        )
        assert decision.state is expected_state and not decision.admission_ready
        zero_effect_results[case] = ScenarioResult(effects, effects, f"{case}-window")

    no_credit = _reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT)
    blocked_quota = RotationQuotaReservationEvidence(
        evaluation=EVALUATION,
        operation_id="blocked-op",
        decision=RotationQuotaDecision(
            admitted=False,
            code="rolling_24h_limit",
            count_24h=3,
            count_168h=3,
        ),
    )
    blocked = evaluate_rotation_foundation(
        _weekly(),
        current_member=MEMBER,
        now=NOW,
        reset=no_credit,
        quota=blocked_quota,
    )
    assert blocked.state is RotationFoundationState.QUOTA_BLOCKED
    zero_effect_results["quota_blocked"] = ScenarioResult(effects, effects, "quota_blocked-window")

    foreign = replace(
        EVALUATION,
        evaluation_id="evaluation-b",
        member=replace(MEMBER, account_id="local-seat-b", user_id="user-b", email="member-b@example.com"),
    )
    invalid_reset = RotationResetEvidence(
        evaluation=foreign,
        resolution=RotationResetCreditResolution(
            status=RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT,
            redeem_request_id=foreign.redeem_request_id,
            account_id=foreign.member.account_id,
            workspace_account_id=foreign.workspace_account_id,
        ),
    )
    invalid = evaluate_rotation_foundation(
        _weekly(),
        current_member=MEMBER,
        now=NOW,
        reset=invalid_reset,
    )
    assert invalid.state is RotationFoundationState.INVALID_EVIDENCE
    zero_effect_results["invalid_evidence"] = ScenarioResult(effects, effects, "invalid_evidence-window")

    mismatch = evaluate_rotation_foundation(
        _weekly(),
        current_member=replace(MEMBER, user_id="user-other"),
        now=NOW,
    )
    assert mismatch.state is RotationFoundationState.USAGE_UNKNOWN and mismatch.weekly_reason == "identity_mismatch"
    zero_effect_results["owner_member_mismatch"] = ScenarioResult(effects, effects, "owner_member_mismatch-window")

    p4_capability = qualify_effect_gate(
        feature_enabled=True,
        foundation_admission_ready=True,
        p4_capability_verified=False,
        p4_provenance_verified=True,
    )
    assert not p4_capability.authorized and p4_capability.code == "p4_capability_unavailable"
    zero_effect_results["p4_capability_unavailable"] = ScenarioResult(
        effects,
        effects,
        "p4_capability_unavailable-window",
    )

    p4_provenance = qualify_effect_gate(
        feature_enabled=True,
        foundation_admission_ready=True,
        p4_capability_verified=True,
        p4_provenance_verified=False,
    )
    assert not p4_provenance.authorized and p4_provenance.code == "p4_provenance_unavailable"
    zero_effect_results["p4_provenance_unavailable"] = ScenarioResult(
        effects,
        effects,
        "p4_provenance_unavailable-window",
    )

    qualify_scenario_matrix(zero_effect_results, required=FAILURE_BOUNDARY_CASES)


def test_fresh_five_hour_does_not_override_elapsed_weekly_at_final_admission() -> None:
    receipt = _receipt(weekly_reset_at=int((NOW + timedelta(seconds=1)).timestamp()))
    assert receipt.five_hour_window is not None
    assert receipt.five_hour_window.reset_at == int((NOW + timedelta(hours=1)).timestamp())
    weekly = bind_rotation_weekly_evidence(receipt, EVALUATION)

    decision = evaluate_rotation_foundation(
        weekly,
        current_member=MEMBER,
        now=NOW + timedelta(seconds=2),
        reset=_reset(RotationResetCreditResolutionStatus.CONFIRMED_NO_REDEEMABLE_CREDIT),
    )

    assert decision.state is RotationFoundationState.USAGE_UNKNOWN
    assert decision.weekly_reason == "reset_elapsed"
    assert not decision.admission_ready


@pytest.mark.parametrize("effect", ["remove", "invite"])
async def test_unknown_effect_remains_represented_and_holds_quota(effect: Literal["remove", "invite"]) -> None:
    current = NOW

    def clock() -> datetime:
        return current

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            repository = RotationQuotaRepository(session, clock=clock)
            decision = await repository.reserve(
                operation_id=f"unknown-{effect}",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
            )
            assert decision.admitted
            row = await repository.record_effect_request(f"unknown-{effect}", effect=effect)
            assert getattr(row, f"{effect}_effect") == "unknown"

            current = NOW + timedelta(days=8)
            snapshot = await repository.snapshot(
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                observed_at=current,
            )
            assert snapshot.count_24h == 1 and snapshot.count_168h == 1
            assert not await repository.release_reservation(f"unknown-{effect}")
    finally:
        await engine.dispose()


async def test_p7_quota_matrix_exercises_exact_24h_and_168h_boundaries() -> None:
    current = NOW

    def clock() -> datetime:
        return current

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            repository = RotationQuotaRepository(session, clock=clock)
            for index, at in enumerate((NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW), start=1):
                current = at
                decision = await repository.reserve(
                    operation_id=f"day-{index}",
                    workspace_id=WORKSPACE_ID,
                    workspace_account_id=WORKSPACE_ACCOUNT_ID,
                )
                assert decision.admitted
            assert decision.count_24h == 3
            current = NOW + timedelta(minutes=1)
            blocked = await repository.reserve(
                operation_id="day-4",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
            )
            assert not blocked.admitted and blocked.code == "rolling_24h_limit" and blocked.count_24h == 3
    finally:
        await engine.dispose()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            repository = RotationQuotaRepository(session, clock=clock)
            for index, days_ago in enumerate((6, 5, 4, 3, 2, 1.1), start=1):
                current = NOW - timedelta(days=days_ago)
                operation_id = f"week-{index}"
                decision = await repository.reserve(
                    operation_id=operation_id,
                    workspace_id=WORKSPACE_ID,
                    workspace_account_id=WORKSPACE_ACCOUNT_ID,
                )
                assert decision.admitted
                current += timedelta(seconds=1)
                await repository.record_effect_request(operation_id, effect="remove")
                current += timedelta(seconds=1)
                await repository.record_effect_outcome(operation_id, effect="remove", outcome="confirmed")
                current += timedelta(seconds=1)
                await repository.mark_completed(operation_id)
            current = NOW
            seventh = await repository.reserve(
                operation_id="week-7",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
            )
            assert seventh.admitted and seventh.count_168h == 7
            current = NOW + timedelta(minutes=1)
            eighth = await repository.reserve(
                operation_id="week-8",
                workspace_id=WORKSPACE_ID,
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
            )
            assert not eighth.admitted and eighth.code == "rolling_168h_limit" and eighth.count_168h == 7
    finally:
        await engine.dispose()


async def test_p7_quota_confirmed_effect_uses_effect_time_and_invalid_metadata_fails_closed() -> None:
    current = NOW - timedelta(days=8)

    def clock() -> datetime:
        return current

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            repository = RotationQuotaRepository(session, clock=clock)
            assert (
                await repository.reserve(
                    operation_id="effect-time",
                    workspace_id=WORKSPACE_ID,
                    workspace_account_id=WORKSPACE_ACCOUNT_ID,
                )
            ).admitted
            current = NOW
            await repository.record_effect_request("effect-time", effect="remove")
            current = NOW + timedelta(seconds=1)
            await repository.record_effect_outcome("effect-time", effect="remove", outcome="confirmed")
            recent = await repository.snapshot(
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                observed_at=NOW + timedelta(seconds=2),
            )
            assert recent.count_24h == 1 and recent.count_168h == 1
            aged = await repository.snapshot(
                workspace_account_id=WORKSPACE_ACCOUNT_ID,
                observed_at=NOW + timedelta(hours=169),
            )
            assert aged.count_24h == 0 and aged.count_168h == 0
    finally:
        await engine.dispose()

    for mode in ("missing", "impossible"):
        current = NOW - timedelta(days=8)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                repository = RotationQuotaRepository(session, clock=clock)
                assert (
                    await repository.reserve(
                        operation_id=f"{mode}-effect-time",
                        workspace_id=WORKSPACE_ID,
                        workspace_account_id=WORKSPACE_ACCOUNT_ID,
                    )
                ).admitted
                row = await session.get(MemberRotationQuotaOperation, f"{mode}-effect-time")
                assert row is not None
                row.remove_requested_at = NOW.replace(tzinfo=None)
                row.remove_effect = "confirmed"
                row.remove_effect_at = None if mode == "missing" else (NOW - timedelta(days=9)).replace(tzinfo=None)
                row.completed_at = NOW.replace(tzinfo=None)
                await session.commit()
                held = await repository.snapshot(
                    workspace_account_id=WORKSPACE_ACCOUNT_ID,
                    observed_at=NOW + timedelta(days=8),
                )
                assert held.count_24h == 1 and held.count_168h == 1
        finally:
            await engine.dispose()


def test_quota_policy_has_no_p4_billed_seat_or_server_threshold_override() -> None:
    import inspect

    reserve_parameters = inspect.signature(RotationQuotaRepository.reserve).parameters
    assert "billed_seat_delta" not in reserve_parameters
    assert "server_threshold" not in reserve_parameters


def test_feature_off_is_a_zero_effect_gate_and_configuration_change_is_observation_only() -> None:
    decision = qualify_effect_gate(
        feature_enabled=False,
        foundation_admission_ready=True,
        p4_capability_verified=True,
        p4_provenance_verified=True,
    )
    assert decision == replace(decision, authorized=False, code="feature_off")
    qualify_scenario_matrix(
        {
            "candidate_deployed_feature_off": ScenarioResult(
                ExternalEffects(),
                ExternalEffects(),
                "candidate-feature-off-window",
            )
        },
        required=("candidate_deployed_feature_off",),
    )


@dataclass
class DurableNoReplayState:
    effects: dict[str, int] = field(
        default_factory=lambda: {
            "reset_consume": 0,
            "remove": 0,
            "invite": 0,
            "join": 0,
            "oauth": 0,
        }
    )
    reads: dict[str, int] = field(default_factory=lambda: {"reset_consume": 0, "remove": 0, "invite": 0})
    unresolved: set[str] = field(default_factory=set)
    receipts: dict[str, DurableEffectReceipt] = field(default_factory=dict)


class ReferenceNoReplayAdapter:
    def __init__(
        self,
        durable: DurableNoReplayState | None = None,
        *,
        replay_on_reconcile: bool = False,
        wrong_receipt_on_reconcile: bool = False,
        collateral_effect: Literal["join", "oauth"] | None = None,
    ) -> None:
        self.durable = durable or DurableNoReplayState()
        self.replay_on_reconcile = replay_on_reconcile
        self.wrong_receipt_on_reconcile = wrong_receipt_on_reconcile
        self.collateral_effect = collateral_effect

    async def cross_effect_boundary_and_lose_response(self, effect: EffectKind) -> None:
        self.durable.effects[effect] += 1
        if self.collateral_effect is not None:
            self.durable.effects[self.collateral_effect] += 1
        self.durable.unresolved.add(effect)
        self.durable.receipts[effect] = DurableEffectReceipt(
            operation_id=f"operation-{effect}",
            effect=effect,
            receipt_id=f"receipt-{effect}-1",
        )

    def restart(self) -> ReferenceNoReplayAdapter:
        return type(self)(
            self.durable,
            replay_on_reconcile=self.replay_on_reconcile,
            wrong_receipt_on_reconcile=self.wrong_receipt_on_reconcile,
            collateral_effect=self.collateral_effect,
        )

    async def reconcile_read_only(
        self,
        effect: EffectKind,
        receipt: DurableEffectReceipt,
    ) -> DurableEffectReceipt:
        self.durable.reads[effect] += 1
        if self.replay_on_reconcile:
            self.durable.effects[effect] += 1
        if self.wrong_receipt_on_reconcile:
            return replace(receipt, receipt_id=f"wrong-{receipt.receipt_id}")
        return self.durable.receipts[effect]

    def effects(self) -> ExternalEffects:
        return ExternalEffects(**self.durable.effects)

    def durable_effect_receipt(self, effect: EffectKind) -> DurableEffectReceipt | None:
        return self.durable.receipts.get(effect)


@pytest.mark.parametrize("effect", ["reset_consume", "remove", "invite"])
async def test_restart_no_replay_protocol_crosses_once_then_reads_only(
    effect: Literal["reset_consume", "remove", "invite"],
) -> None:
    adapter = ReferenceNoReplayAdapter()

    await qualify_restart_no_replay(adapter, effect)

    assert adapter.durable.effects[effect] == 1
    assert adapter.durable.reads[effect] == 1
    assert effect in adapter.durable.unresolved
    assert adapter.durable.receipts[effect].operation_id == f"operation-{effect}"


@pytest.mark.parametrize("effect", ["reset_consume", "remove", "invite"])
async def test_restart_no_replay_protocol_rejects_a_false_positive_replaying_adapter(
    effect: Literal["reset_consume", "remove", "invite"],
) -> None:
    adapter = ReferenceNoReplayAdapter(replay_on_reconcile=True)

    with pytest.raises(QualificationError, match="replayed an external effect"):
        await qualify_restart_no_replay(adapter, effect)


@pytest.mark.parametrize("effect", ["reset_consume", "remove", "invite"])
async def test_restart_no_replay_protocol_rejects_wrong_authoritative_receipt(
    effect: Literal["reset_consume", "remove", "invite"],
) -> None:
    adapter = ReferenceNoReplayAdapter(wrong_receipt_on_reconcile=True)

    with pytest.raises(QualificationError, match="same durable receipt"):
        await qualify_restart_no_replay(adapter, effect)


@pytest.mark.parametrize("effect", ["reset_consume", "remove", "invite"])
@pytest.mark.parametrize("collateral", ["join", "oauth"])
async def test_restart_no_replay_protocol_rejects_collateral_external_effects(
    effect: Literal["reset_consume", "remove", "invite"],
    collateral: Literal["join", "oauth"],
) -> None:
    adapter = ReferenceNoReplayAdapter(collateral_effect=collateral)

    with pytest.raises(QualificationError, match=f"unexpectedly emitted {collateral}"):
        await qualify_restart_no_replay(adapter, effect)


def _p4_observations() -> list[TelemetryObservation]:
    fixture = json.loads(P4_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == 1
    observations: list[TelemetryObservation] = []
    for raw in fixture["observations"]:
        observations.append(
            TelemetryObservation(
                operation=raw["operation"],
                case=raw["case"],
                capture_state=raw["capture_state"],
                value_present=raw.get("value_present", False),
                value=raw.get("value"),
                sensitive_values_retained=raw.get("sensitive_values_retained", False),
            )
        )
    return observations


def test_p4_typed_remove_and_invite_fixture_matrix_is_complete_and_type_strict() -> None:
    qualify_p4_telemetry_matrix(_p4_observations())

    unsafe = _p4_observations()
    boolean_index = next(
        index for index, item in enumerate(unsafe) if item.operation == "invite" and item.case == "boolean"
    )
    unsafe[boolean_index] = replace(unsafe[boolean_index], value=1)
    with pytest.raises(QualificationError, match="boolean type"):
        qualify_p4_telemetry_matrix(unsafe)

    leaking = _p4_observations()
    sensitive_index = next(
        index
        for index, item in enumerate(leaking)
        if item.operation == "remove" and item.case == "sensitive_nested_dynamic"
    )
    leaking[sensitive_index] = replace(leaking[sensitive_index], sensitive_values_retained=True)
    with pytest.raises(QualificationError, match="sensitive nested/dynamic"):
        qualify_p4_telemetry_matrix(leaking)


def test_final_usage_retention_must_precede_remove_authority() -> None:
    qualify_retention_before_remove(("final_usage_retained", "remove_authority_committed"))
    with pytest.raises(QualificationError, match="before final Usage retention"):
        qualify_retention_before_remove(("remove_authority_committed", "final_usage_retained"))


def test_concurrency_matrix_requires_every_zero_effect_scenario() -> None:
    results = {
        case: ScenarioResult(ExternalEffects(), ExternalEffects(), f"{case}-observation-window")
        for case in CONCURRENCY_CASES
    }
    qualify_scenario_matrix(results, required=CONCURRENCY_CASES)

    missing = dict(results)
    missing.pop("claim_lease_expiry")
    with pytest.raises(QualificationError, match="missing scenarios"):
        qualify_scenario_matrix(missing, required=CONCURRENCY_CASES)

    replaying = dict(results)
    replaying["companion_restart"] = ScenarioResult(
        ExternalEffects(),
        ExternalEffects(invite=1),
        "companion_restart-replay-window",
    )
    with pytest.raises(QualificationError, match="external effect count changed"):
        qualify_scenario_matrix(replaying, required=CONCURRENCY_CASES)

    reused = dict(results)
    reused["backend_restart"] = replace(
        reused["backend_restart"],
        observation_id=reused["companion_restart"].observation_id,
    )
    with pytest.raises(QualificationError, match="observation identity was reused"):
        qualify_scenario_matrix(reused, required=CONCURRENCY_CASES)


def _valid_preflight() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "subject": {"workspace_account_id": WORKSPACE_ACCOUNT_ID},
        "candidate": {
            "source_sha": "a" * 40,
            "package_version": "1.25.0-beta.9",
            "image_sha256": "b" * 64,
            "provenance_verified": True,
        },
        "p4": {
            "version": P4_VERSION,
            "binary_sha256": P4_BINARY_SHA256,
            "patch_sha256": P4_PATCH_SHA256,
            "patch_uncompressed_sha256": P4_PATCH_UNCOMPRESSED_SHA256,
            "artifact_owning_ops_commit": P4_OWNING_OPS_COMMIT,
            "reconstructed_source_baseline": P4_RECONSTRUCTION_BASELINE,
            "capability_verified": True,
            "provenance_verified": True,
            "contract": sorted(P4_CONTRACT),
        },
        "postgres": {
            "gate": "PASS",
            "container_id": POSTGRES_CONTAINER_ID,
            "container_started_at": "2026-09-13T01:31:43.765554503Z",
            "system_identifier": POSTGRES_SYSTEM_IDENTIFIER,
            "current_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
            "official_head_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
            "member_rotation_extension_contract": MEMBER_ROTATION_EXTENSION_CONTRACT,
            "member_rotation_extension_gate": "PASS",
            "snapshot_fingerprint": POSTGRES_SNAPSHOT,
            "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
        },
        "migration": {
            "policy": "PASS",
            "schema_drift": "PASS",
            "database_container_id": POSTGRES_CONTAINER_ID,
            "database_container_started_at": "2026-09-13T01:31:43.765554503Z",
            "system_identifier": POSTGRES_SYSTEM_IDENTIFIER,
            "current_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
            "head_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
            "candidate_head_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
            "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
            "postgres_snapshot_fingerprint": POSTGRES_SNAPSHOT,
        },
        "operations": {
            "active_member_switch_controls": 0,
            "active_oauth_member_operations": 0,
            "oauth_device_slots": 0,
            "automatic_rotation_enabled_rows": 0,
            "postgres_snapshot_fingerprint": POSTGRES_SNAPSHOT,
        },
        "runtime": {
            "stable_before_sha256": STABLE_SHA256,
            "stable_after_sha256": STABLE_SHA256,
            "beta_before_sha256": BETA_SHA256,
            "beta_after_sha256": BETA_SHA256,
            "postgres_snapshot_fingerprint": POSTGRES_SNAPSHOT,
        },
        "feature": {
            "default_enabled": False,
            "enabled": False,
            "configuration_effects": {
                "reset_consume": 0,
                "remove": 0,
                "invite": 0,
                "join": 0,
                "oauth": 0,
            },
            "automatic_effects_during_off_window": {
                "reset_consume": 0,
                "remove": 0,
                "invite": 0,
                "join": 0,
                "oauth": 0,
            },
            "postgres_snapshot_fingerprint": POSTGRES_SNAPSHOT,
        },
        "rollback": {
            "exists": True,
            "identity_sha256": ROLLBACK_SHA256,
            "verified": True,
            "strategy": "restore_pre_migration_database",
            "post_migration_predecessor_boundary": {
                "stable": {
                    "probe_kind": "migration_state",
                    "compatible": False,
                    "image_sha256": ROLLBACK_STABLE_SHA256,
                    "source_sha": ROLLBACK_STABLE_SOURCE_SHA,
                    "role": STABLE_ROLE,
                    "database_container_id": POSTGRES_CONTAINER_ID,
                    "database_container_started_at": "2026-09-13T01:31:43.765554503Z",
                    "system_identifier": POSTGRES_SYSTEM_IDENTIFIER,
                    "current_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
                    "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                    "needs_upgrade": True,
                    "is_ahead": True,
                    "unknown_revisions": [PRODUCTION_OFFICIAL_ALEMBIC_HEAD],
                    "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
                    "postgres_snapshot_fingerprint": POSTGRES_SNAPSHOT,
                },
                "beta": {
                    "probe_kind": "migration_state",
                    "compatible": False,
                    "image_sha256": ROLLBACK_BETA_SHA256,
                    "source_sha": ROLLBACK_BETA_SOURCE_SHA,
                    "role": BETA_ROLE,
                    "database_container_id": POSTGRES_CONTAINER_ID,
                    "database_container_started_at": "2026-09-13T01:31:43.765554503Z",
                    "system_identifier": POSTGRES_SYSTEM_IDENTIFIER,
                    "current_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
                    "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                    "needs_upgrade": True,
                    "is_ahead": True,
                    "unknown_revisions": [PRODUCTION_OFFICIAL_ALEMBIC_HEAD],
                    "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
                    "postgres_snapshot_fingerprint": POSTGRES_SNAPSHOT,
                },
            },
            "source_database": {
                "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "member_rotation_extension_preserved": True,
                "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
                "extension_tables": _extension_table_fingerprints(),
                "snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
                "backup_identity_sha256": ROLLBACK_SHA256,
                "legacy_credential_columns": list(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS),
                "legacy_credential_fingerprint_sha256": ROLLBACK_CREDENTIAL_FINGERPRINT,
                "retired_sentinel_present": False,
            },
            "restore_rehearsal": {
                "database_container_id": ROLLBACK_DATABASE_CONTAINER_ID,
                "database_container_started_at": "2026-09-16T00:00:00Z",
                "system_identifier": ROLLBACK_DATABASE_SYSTEM_IDENTIFIER,
                "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "member_rotation_extension_preserved": True,
                "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
                "extension_tables": _extension_table_fingerprints(),
                "snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
                "source_snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
                "backup_identity_sha256": ROLLBACK_SHA256,
                "legacy_credential_columns": list(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS),
                "legacy_credential_fingerprint_sha256": ROLLBACK_CREDENTIAL_FINGERPRINT,
                "retired_sentinel_present": False,
            },
            "predecessor": {
                "stable_image_sha256": ROLLBACK_STABLE_SHA256,
                "beta_image_sha256": ROLLBACK_BETA_SHA256,
                "stable_source_sha": ROLLBACK_STABLE_SOURCE_SHA,
                "beta_source_sha": ROLLBACK_BETA_SOURCE_SHA,
                "stable_role": STABLE_ROLE,
                "beta_role": BETA_ROLE,
            },
            "stable_start_probe": {
                "probe_kind": "runtime_start",
                "compatible": True,
                "image_sha256": ROLLBACK_STABLE_SHA256,
                "source_sha": ROLLBACK_STABLE_SOURCE_SHA,
                "role": STABLE_ROLE,
                "container_id": ROLLBACK_STABLE_CONTAINER_ID,
                "container_started_at": "2026-09-16T00:01:00Z",
                "running": True,
                "ready": True,
                "readiness_path": "/health/ready",
                "readiness_status": 200,
                "restart_count": 0,
                "migrate_on_startup": False,
                "database_container_id": ROLLBACK_DATABASE_CONTAINER_ID,
                "database_container_started_at": "2026-09-16T00:00:00Z",
                "system_identifier": ROLLBACK_DATABASE_SYSTEM_IDENTIFIER,
                "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "needs_upgrade": False,
                "is_ahead": False,
                "unknown_revisions": [],
                "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
                "postgres_snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
            },
            "beta_start_probe": {
                "probe_kind": "runtime_start",
                "compatible": True,
                "image_sha256": ROLLBACK_BETA_SHA256,
                "source_sha": ROLLBACK_BETA_SOURCE_SHA,
                "role": BETA_ROLE,
                "container_id": ROLLBACK_BETA_CONTAINER_ID,
                "container_started_at": "2026-09-16T00:02:00Z",
                "running": True,
                "ready": True,
                "readiness_path": "/health/ready",
                "readiness_status": 200,
                "restart_count": 0,
                "migrate_on_startup": False,
                "database_container_id": ROLLBACK_DATABASE_CONTAINER_ID,
                "database_container_started_at": "2026-09-16T00:00:00Z",
                "system_identifier": ROLLBACK_DATABASE_SYSTEM_IDENTIFIER,
                "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "needs_upgrade": False,
                "is_ahead": False,
                "unknown_revisions": [],
                "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
                "postgres_snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
            },
        },
    }


def _set_nested(document: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    current = document
    for key in path[:-1]:
        current = cast(dict[str, Any], current[key])
    current[path[-1]] = value


def test_preflight_requires_exact_candidate_p4_pg_idle_runtime_feature_and_rollback_evidence() -> None:
    result = verify_preflight(
        _valid_preflight(),
        expected_source_sha="a" * 40,
        expected_package_version="1.25.0-beta.9",
        expected_image_sha256="b" * 64,
        expected_workspace_account_id=WORKSPACE_ACCOUNT_ID,
        expected_stable_sha256=STABLE_SHA256,
        expected_beta_sha256=BETA_SHA256,
        expected_postgres_container_id=POSTGRES_CONTAINER_ID,
        expected_postgres_system_identifier=POSTGRES_SYSTEM_IDENTIFIER,
        expected_rollback_stable_sha256=ROLLBACK_STABLE_SHA256,
        expected_rollback_beta_sha256=ROLLBACK_BETA_SHA256,
        expected_rollback_stable_source_sha=ROLLBACK_STABLE_SOURCE_SHA,
        expected_rollback_beta_source_sha=ROLLBACK_BETA_SOURCE_SHA,
        expected_rollback_stable_role=STABLE_ROLE,
        expected_rollback_beta_role=BETA_ROLE,
    )
    assert result["workspace_account_id"] == WORKSPACE_ACCOUNT_ID
    assert result["source_sha"] == "a" * 40
    assert result["image_sha256"] == "b" * 64
    assert result["stable_sha256"] == STABLE_SHA256
    assert result["beta_sha256"] == BETA_SHA256
    assert result["postgres_container_id"] == POSTGRES_CONTAINER_ID
    assert result["postgres_system_identifier"] == POSTGRES_SYSTEM_IDENTIFIER
    assert result["postgres_snapshot_fingerprint"] == POSTGRES_SNAPSHOT


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("subject", "workspace_account_id"), "wrong-workspace", "workspace account identity mismatch"),
        (("candidate", "image_sha256"), "c" * 64, "candidate image SHA mismatch"),
        (("p4", "patch_uncompressed_sha256"), "c" * 64, "decompressed artifact SHA mismatch"),
        (("p4", "provenance_verified"), False, "P4 provenance is unavailable"),
        (("p4", "capability_verified"), False, "P4 capability is unavailable"),
        (("p4", "contract"), [], "P4 contract evidence is incomplete"),
        (("postgres", "gate"), "FAIL", "PostgreSQL gate did not pass"),
        (("postgres", "container_id"), "1" * 64, "PostgreSQL container identity mismatch"),
        (("postgres", "container_started_at"), "", "PostgreSQL start identity missing"),
        (("postgres", "system_identifier"), "123", "PostgreSQL system identifier mismatch"),
        (("postgres", "current_revision"), "wrong", "current revision is not the official production head"),
        (("postgres", "member_rotation_extension_gate"), "FAIL", "extension PostgreSQL gate did not pass"),
        (("postgres", "snapshot_fingerprint"), "not-a-sha", "snapshot_fingerprint is not a SHA-256"),
        (("postgres", "extension_schema_sha256"), "not-a-sha", "extension_schema_sha256 is not a SHA-256"),
        (("migration", "policy"), "FAIL", "migration policy gate did not pass"),
        (("migration", "schema_drift"), "FAIL", "migration schema-drift gate did not pass"),
        (("migration", "database_container_id"), "1" * 64, "migration evidence is not bound"),
        (("migration", "database_container_started_at"), "different", "migration evidence is not bound"),
        (("migration", "head_revision"), "wrong", "migration evidence is not at the official production head"),
        (
            ("migration", "candidate_head_revision"),
            "wrong",
            "candidate Alembic head is not the official production head",
        ),
        (("migration", "extension_schema_sha256"), "1" * 64, "migration evidence extension schema mismatch"),
        (("migration", "postgres_snapshot_fingerprint"), "1" * 64, "not from the admitted PostgreSQL snapshot"),
        (("operations", "active_member_switch_controls"), 1, "active member-switch control exists"),
        (("operations", "active_oauth_member_operations"), 1, "active OAuth/member operation exists"),
        (("operations", "oauth_device_slots"), 1, "active OAuth device-flow slot exists"),
        (("operations", "automatic_rotation_enabled_rows"), 1, "automatic rotation intent is enabled"),
        (("runtime", "stable_after_sha256"), "f" * 64, "Stable identity changed"),
        (("runtime", "beta_after_sha256"), "f" * 64, "Beta identity changed"),
        (("runtime", "postgres_snapshot_fingerprint"), "1" * 64, "runtime evidence is not bound"),
        (("feature", "default_enabled"), True, "not default OFF"),
        (("feature", "enabled"), True, "enabled during preflight"),
        (
            ("feature", "automatic_effects_during_off_window", "invite"),
            1,
            "feature OFF observation window",
        ),
        (("feature", "postgres_snapshot_fingerprint"), "1" * 64, "feature evidence is not bound"),
        (("rollback", "exists"), False, "rollback artifact does not exist"),
        (("rollback", "strategy"), "alembic_downgrade", "restore the verified pre-migration database"),
        (
            ("rollback", "post_migration_predecessor_boundary", "stable", "compatible"),
            True,
            "Stable unexpectedly accepts the beta.9 database",
        ),
        (
            ("rollback", "post_migration_predecessor_boundary", "beta", "unknown_revisions"),
            [],
            "Beta predecessor did not prove the non-rolling beta.9 migration boundary",
        ),
        (
            ("rollback", "source_database", "current_revision"),
            "wrong",
            "source database is not at the predecessor official head",
        ),
        (
            ("rollback", "source_database", "backup_identity_sha256"),
            "0" * 64,
            "source database is not bound to the verified backup artifact",
        ),
        (
            ("rollback", "source_database", "extension_tables", "member_switch_control_records", "count"),
            99,
            "restore changed local extension table data fingerprints",
        ),
        (
            ("rollback", "source_database", "legacy_credential_fingerprint_sha256"),
            "1" * 64,
            "dashboard credential state",
        ),
        (
            ("rollback", "restore_rehearsal", "current_revision"),
            "wrong",
            "restored database is not at the predecessor official head",
        ),
        (
            ("rollback", "restore_rehearsal", "source_snapshot_fingerprint"),
            "1" * 64,
            "exact pre-migration snapshot restore",
        ),
        (
            ("rollback", "restore_rehearsal", "backup_identity_sha256"),
            "1" * 64,
            "verified backup artifact",
        ),
        (
            ("rollback", "restore_rehearsal", "extension_tables", "member_rotation_workspace_controls", "count"),
            99,
            "changed local extension table data fingerprints",
        ),
        (("rollback", "predecessor", "stable_image_sha256"), "7" * 64, "Stable predecessor identity mismatch"),
        (
            ("rollback", "predecessor", "stable_source_sha"),
            "1" * 40,
            "Stable predecessor release identity mismatch",
        ),
        (("rollback", "stable_start_probe", "probe_kind"), "wrong", "Stable rollback probe kind is invalid"),
        (("rollback", "stable_start_probe", "compatible"), False, "Stable rollback DB compatibility was not verified"),
        (
            ("rollback", "stable_start_probe", "ready"),
            False,
            "Stable rollback predecessor did not prove a clean ready startup",
        ),
        (
            ("rollback", "stable_start_probe", "container_started_at"),
            "2026-09-16T00:00:00Z",
            "Stable rollback predecessor was not started after the restored database epoch",
        ),
        (
            ("rollback", "beta_start_probe", "migrate_on_startup"),
            True,
            "Beta predecessor rollback predecessor did not prove a clean ready startup",
        ),
        (
            ("rollback", "beta_start_probe", "compatible"),
            False,
            "Beta predecessor rollback DB compatibility was not verified",
        ),
        (
            ("rollback", "stable_start_probe", "needs_upgrade"),
            True,
            "Stable rollback migration state is not compatible",
        ),
    ],
)
def test_preflight_fails_closed_on_each_release_boundary(path: tuple[str, ...], value: object, message: str) -> None:
    evidence = copy.deepcopy(_valid_preflight())
    _set_nested(evidence, path, value)

    with pytest.raises(QualificationError, match=message):
        verify_preflight(
            evidence,
            expected_source_sha="a" * 40,
            expected_package_version="1.25.0-beta.9",
            expected_image_sha256="b" * 64,
            expected_workspace_account_id=WORKSPACE_ACCOUNT_ID,
            expected_stable_sha256=STABLE_SHA256,
            expected_beta_sha256=BETA_SHA256,
            expected_postgres_container_id=POSTGRES_CONTAINER_ID,
            expected_postgres_system_identifier=POSTGRES_SYSTEM_IDENTIFIER,
            expected_rollback_stable_sha256=ROLLBACK_STABLE_SHA256,
            expected_rollback_beta_sha256=ROLLBACK_BETA_SHA256,
            expected_rollback_stable_source_sha=ROLLBACK_STABLE_SOURCE_SHA,
            expected_rollback_beta_source_sha=ROLLBACK_BETA_SOURCE_SHA,
            expected_rollback_stable_role=STABLE_ROLE,
            expected_rollback_beta_role=BETA_ROLE,
        )


def _rollback_state(*, restored: bool = False) -> dict[str, Any]:
    state: dict[str, Any] = {
        key: {
            "count": index,
            "sha256": hashlib.sha256(key.encode()).hexdigest(),
        }
        for index, key in enumerate(ROLLBACK_STATE_KEYS, start=1)
    }
    state["database"] = {
        "container_id": ROLLBACK_DATABASE_CONTAINER_ID if restored else POSTGRES_CONTAINER_ID,
        "container_started_at": "2026-09-16T00:00:00Z" if restored else "2026-09-15T00:00:00Z",
        "system_identifier": ROLLBACK_DATABASE_SYSTEM_IDENTIFIER if restored else POSTGRES_SYSTEM_IDENTIFIER,
        "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "extension_contract": MEMBER_ROTATION_EXTENSION_CONTRACT,
        "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
        "snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
        "backup_identity_sha256": ROLLBACK_SHA256,
        "legacy_credential_columns": list(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS),
        "legacy_credential_fingerprint_sha256": ROLLBACK_CREDENTIAL_FINGERPRINT,
        "retired_sentinel_present": False,
    }
    if restored:
        state["database"].update(
            source_snapshot_fingerprint=ROLLBACK_DATABASE_SNAPSHOT,
            restore_verified=True,
        )
    state["extension_tables"] = {
        table: {"count": index, "sha256": hashlib.sha256(table.encode()).hexdigest()}
        for index, table in enumerate(ROLLBACK_EXTENSION_TABLES, start=1)
    }
    if restored:
        state["predecessor"] = {
            "stable_image_sha256": ROLLBACK_STABLE_SHA256,
            "beta_image_sha256": ROLLBACK_BETA_SHA256,
            "stable_source_sha": ROLLBACK_STABLE_SOURCE_SHA,
            "beta_source_sha": ROLLBACK_BETA_SOURCE_SHA,
            "stable_role": STABLE_ROLE,
            "beta_role": BETA_ROLE,
        }
        state["predecessor_start_probes"] = {
            "stable": {
                "probe_kind": "runtime_start",
                "compatible": True,
                "image_sha256": ROLLBACK_STABLE_SHA256,
                "source_sha": ROLLBACK_STABLE_SOURCE_SHA,
                "role": STABLE_ROLE,
                "container_id": ROLLBACK_STABLE_CONTAINER_ID,
                "container_started_at": "2026-09-16T00:01:00Z",
                "running": True,
                "ready": True,
                "readiness_path": "/health/ready",
                "readiness_status": 200,
                "restart_count": 0,
                "migrate_on_startup": False,
                "database_container_id": ROLLBACK_DATABASE_CONTAINER_ID,
                "database_container_started_at": "2026-09-16T00:00:00Z",
                "system_identifier": ROLLBACK_DATABASE_SYSTEM_IDENTIFIER,
                "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "needs_upgrade": False,
                "is_ahead": False,
                "unknown_revisions": [],
                "postgres_snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
                "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
            },
            "beta": {
                "probe_kind": "runtime_start",
                "compatible": True,
                "image_sha256": ROLLBACK_BETA_SHA256,
                "source_sha": ROLLBACK_BETA_SOURCE_SHA,
                "role": BETA_ROLE,
                "container_id": ROLLBACK_BETA_CONTAINER_ID,
                "container_started_at": "2026-09-16T00:02:00Z",
                "running": True,
                "ready": True,
                "readiness_path": "/health/ready",
                "readiness_status": 200,
                "restart_count": 0,
                "migrate_on_startup": False,
                "database_container_id": ROLLBACK_DATABASE_CONTAINER_ID,
                "database_container_started_at": "2026-09-16T00:00:00Z",
                "system_identifier": ROLLBACK_DATABASE_SYSTEM_IDENTIFIER,
                "current_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
                "needs_upgrade": False,
                "is_ahead": False,
                "unknown_revisions": [],
                "postgres_snapshot_fingerprint": ROLLBACK_DATABASE_SNAPSHOT,
                "extension_schema_sha256": EXTENSION_SCHEMA_SHA256,
            },
        }
    return state


def _verify_rollback(before: dict[str, Any], after: dict[str, Any]) -> None:
    verify_rollback_state(
        before,
        after,
        expected_rollback_stable_sha256=ROLLBACK_STABLE_SHA256,
        expected_rollback_beta_sha256=ROLLBACK_BETA_SHA256,
        expected_rollback_stable_source_sha=ROLLBACK_STABLE_SOURCE_SHA,
        expected_rollback_beta_source_sha=ROLLBACK_BETA_SOURCE_SHA,
        expected_rollback_stable_role=STABLE_ROLE,
        expected_rollback_beta_role=BETA_ROLE,
    )


def test_rollback_requires_exact_durable_state_preservation() -> None:
    before = _rollback_state()
    restored = _rollback_state(restored=True)
    _verify_rollback(before, restored)

    for key in ROLLBACK_STATE_KEYS:
        after = copy.deepcopy(restored)
        after[key]["count"] += 1
        with pytest.raises(QualificationError, match=key):
            _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["database"]["current_revision"] = "wrong"
    with pytest.raises(QualificationError, match="restored rollback database is not at the predecessor official head"):
        _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["database"]["source_snapshot_fingerprint"] = "0" * 64
    with pytest.raises(QualificationError, match="snapshot was not restored exactly"):
        _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["database"]["legacy_credential_fingerprint_sha256"] = "0" * 64
    with pytest.raises(QualificationError, match="dashboard credential state changed"):
        _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["extension_tables"]["member_rotation_workspace_controls"]["count"] += 1
    with pytest.raises(QualificationError, match="extension table member_rotation_workspace_controls"):
        _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["predecessor_start_probes"]["stable"]["compatible"] = False
    with pytest.raises(QualificationError, match="Stable rollback DB compatibility"):
        _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["predecessor"]["beta_source_sha"] = "0" * 40
    with pytest.raises(QualificationError, match="Beta predecessor release identity mismatch"):
        _verify_rollback(before, after)

    after = copy.deepcopy(restored)
    after["predecessor_start_probes"]["beta"]["ready"] = False
    with pytest.raises(
        QualificationError, match="Beta predecessor rollback predecessor did not prove a clean ready startup"
    ):
        _verify_rollback(before, after)


def test_canary_guard_allows_bounded_partial_stop_without_retry_permission() -> None:
    remove_only = verify_canary_events(
        [
            "replacement_started",
            "remove_sent",
            "remove_capture_failed",
            "remove_reconciled",
            "stop_after_remove",
        ]
    )
    assert remove_only["remove_requests"] == 1 and remove_only["invite_requests"] == 0

    invite_only = verify_canary_events(
        [
            "replacement_started",
            "remove_sent",
            "remove_reconciled",
            "invite_sent",
            "invite_capture_failed",
            "invite_reconciled",
            "stop_after_invite",
        ]
    )
    assert invite_only["invite_requests"] == 1 and invite_only["join_confirmed"] is False

    remove_authorization = authorize_canary_effect(["replacement_started"], "remove")
    assert remove_authorization.authorized and remove_authorization.code == "remove_authorized"
    with pytest.raises(QualificationError, match="remove budget already consumed"):
        authorize_canary_effect(
            ["replacement_started", "remove_sent", "remove_capture_failed", "remove_reconciled"],
            "remove",
        )

    invite_authorization = authorize_canary_effect(
        ["replacement_started", "remove_sent", "remove_capture_failed", "remove_reconciled"],
        "invite",
    )
    assert invite_authorization.authorized and invite_authorization.code == "invite_authorized"
    with pytest.raises(QualificationError, match="invite budget already consumed"):
        authorize_canary_effect(
            [
                "replacement_started",
                "remove_sent",
                "remove_reconciled",
                "invite_sent",
                "invite_capture_failed",
                "invite_reconciled",
            ],
            "invite",
        )

    with pytest.raises(QualificationError, match="more than one remove"):
        verify_canary_events(["replacement_started", "remove_sent", "remove_capture_failed", "remove_sent"])
    with pytest.raises(QualificationError, match="without authoritative join confirmation"):
        verify_canary_events(
            [
                "replacement_started",
                "remove_sent",
                "remove_reconciled",
                "invite_sent",
                "invite_reconciled",
                "mark_success",
            ]
        )
    with pytest.raises(QualificationError, match="after reset recovery"):
        verify_canary_events(["reset_recovered", "replacement_started"])
    with pytest.raises(QualificationError, match="before authoritative remove reconciliation"):
        verify_canary_events(["replacement_started", "remove_sent", "invite_sent"])
    with pytest.raises(QualificationError, match="threshold-discovery churn"):
        verify_canary_events(["threshold_probe"])


def test_canary_success_requires_one_invite_and_authoritative_join() -> None:
    result = verify_canary_events(
        [
            "replacement_started",
            "remove_sent",
            "remove_reconciled",
            "invite_sent",
            "invite_reconciled",
            "join_confirmed",
            "mark_success",
        ]
    )
    assert result == {
        "replacement_workflows": 1,
        "remove_requests": 1,
        "invite_requests": 1,
        "reset_recovered": False,
        "join_confirmed": True,
        "remove_reconciled": True,
        "invite_reconciled": True,
    }
