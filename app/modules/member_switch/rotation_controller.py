from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.usage.weekly_observation import RotationUsageObservation, UsageAccountIdentity
from app.modules.member_auth_handoff.rotation_events import (
    RotationEffect,
    RotationEffectOutcome,
    RotationQuotaRepository,
)
from app.modules.member_auth_handoff.usage_snapshot_repository import (
    HistoricalUsageConflict,
    MemberUsageSnapshotRepository,
)
from app.modules.member_switch.admission import local_admission
from app.modules.member_switch.policy import membership_confirmed, pre_membership_failure_confirmed
from app.modules.member_switch.repository import ControlConflict, ControlRecord, MemberSwitchControlRepository
from app.modules.member_switch.rotation_foundation import (
    FinalUsageRetentionUnavailable,
    RotationFoundationReadModel,
    RotationFoundationState,
    RotationQuotaReservationEvidence,
    RotationResetEvidence,
    RotationWeeklyEvidence,
    bind_rotation_weekly_evidence,
    evaluate_rotation_foundation,
    final_usage_snapshot_inputs,
)
from app.modules.member_switch.schemas import (
    CommandRequest,
    CompanionTypedTelemetryProvenance,
    CreateRunRequest,
    Identity,
    Member,
    MemberMutationResponseObservation,
    RotationControllerState,
    Workspace,
)
from app.modules.member_switch.service import MemberSwitchService

_ROTATION_NAMESPACE = uuid5(NAMESPACE_URL, "codex-lb:usage-member-rotation-controller:v1")
_UNSAFE_CAPTURE_STATES = frozenset(
    {
        "json_parse_failure",
        "response_not_received",
        "transport_failure",
        "body_read_failure",
        "sanitization_failure",
        "capture_failure",
    }
)


def _stable_uuid(*parts: str) -> str:
    return str(uuid5(_ROTATION_NAMESPACE, "\n".join(parts)))


def rotation_controller_id(evaluation_id: str) -> str:
    return _stable_uuid("controller", evaluation_id)


def rotation_run_id(evaluation_id: str) -> str:
    return _stable_uuid("run", evaluation_id)


def rotation_start_command_id(evaluation_id: str) -> str:
    return _stable_uuid("start", evaluation_id)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _response_capture_failed(observation: MemberMutationResponseObservation | None) -> bool:
    return observation is not None and observation.capture_state in _UNSAFE_CAPTURE_STATES


def select_rotation_candidate(
    workspace: Workspace,
    *,
    outgoing: UsageAccountIdentity,
) -> tuple[str, Member]:
    """Select only from the workspace candidate allowlist, never the account/OAuth pool."""
    current = [
        member
        for member in workspace.current_members
        if member.email.casefold() == outgoing.email.casefold() and member.user_id == outgoing.user_id
    ]
    if len(current) != 1 or current[0].preset_id is None:
        raise ControlConflict("rotation_outgoing_identity_unresolved")
    if workspace.membership_observed_at is None:
        raise ControlConflict("rotation_membership_not_observed")
    current_emails = {member.email.casefold() for member in workspace.current_members}
    current_user_ids = {member.user_id for member in workspace.current_members}
    candidates = sorted(
        (
            member
            for member in workspace.members
            if member.email.casefold() != workspace.owner_email.casefold()
            and member.email.casefold() != outgoing.email.casefold()
            and member.user_id != outgoing.user_id
            and member.email.casefold() not in current_emails
            and member.user_id not in current_user_ids
        ),
        key=lambda member: (member.preset_id, member.email.casefold(), member.user_id),
    )
    if not candidates:
        raise ControlConflict("rotation_candidate_unavailable")
    return current[0].preset_id, candidates[0]


class RotationController:
    """Durable orchestration around G1 facts and the existing member-switch executor."""

    def __init__(
        self,
        controls: MemberSwitchControlRepository,
        member_switch: MemberSwitchService,
        snapshot_sessions: Callable[[], AsyncSession],
        quota_sessions: Callable[[], AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.controls = controls
        self.member_switch = member_switch
        self._snapshot_sessions = snapshot_sessions
        self._quota_sessions = quota_sessions
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _decode(record: ControlRecord) -> RotationControllerState:
        if record.kind != "rotation":
            raise ControlConflict("rotation_record_identity_mismatch")
        try:
            state = RotationControllerState.model_validate_json(record.payload)
        except ValidationError as exc:
            raise ControlConflict("stored_rotation_review_required") from exc
        if state.id != record.id or record.active_scope is not None or record.pending_action is not None:
            raise ControlConflict("stored_rotation_review_required")
        # ``p4_provenance_verified`` is cached presentation state, not durable
        # authority.  Re-evaluate the exact contract tuple against the current
        # code on every load so a restart after qualification changes cannot
        # authorize a previously previewed external effect.
        return state.model_copy(
            update={
                "p4_provenance_verified": bool(state.p4_provenance and state.p4_provenance.qualified),
            }
        )

    @staticmethod
    def _p4_qualified(state: RotationControllerState) -> bool:
        return bool(state.p4_provenance and state.p4_provenance.qualified)

    @staticmethod
    def _foundation_fields(foundation: RotationFoundationReadModel) -> dict[str, object]:
        return {
            "foundation_state": foundation.state.value,
            "foundation_admission_ready": foundation.admission_ready,
            "foundation_attention_required": foundation.attention_required,
            "foundation_weekly_state": foundation.weekly_state,
            "foundation_weekly_reason": foundation.weekly_reason,
            "reset_status": foundation.reset_status,
            "foundation_quota_code": foundation.quota_code,
            "foundation_count_24h": foundation.count_24h,
            "foundation_count_168h": foundation.count_168h,
        }

    @staticmethod
    def _start_claimed(record: ControlRecord | None, state: RotationControllerState, run) -> bool:
        return bool(run is not None and (run.pending_action == "start" or run.operation_id))

    async def get(self, controller_id: str) -> RotationControllerState | None:
        record = await self.controls.get(controller_id)
        return None if record is None else self._decode(record)

    async def _persist(
        self,
        record: ControlRecord,
        state: RotationControllerState,
    ) -> tuple[ControlRecord, RotationControllerState]:
        state = state.model_copy(update={"updated_at": _utc(self._clock())})
        try:
            saved = await self.controls.save(record, state.model_dump_json(), complete=True)
        except ControlConflict as exc:
            if exc.code != "revision_conflict":
                raise
            latest = await self.controls.get(record.id)
            if latest is None:
                raise
            return latest, self._decode(latest)
        return saved, self._decode(saved)

    async def _create_or_load(self, state: RotationControllerState) -> tuple[ControlRecord, RotationControllerState]:
        existing = await self.controls.get(state.id)
        if existing is None:
            try:
                created = await self.controls.create(state.id, "rotation", state.model_dump_json(), own_scope=False)
            except ControlConflict as exc:
                if exc.code != "flow_busy_or_id_exists":
                    raise
                existing = await self.controls.get(state.id)
                if existing is None:
                    raise
            else:
                return created, self._decode(created)
        assert existing is not None
        stored = self._decode(existing)
        expected = (
            state.evaluation_id,
            state.workspace_id,
            state.workspace_account_id,
            state.outgoing_account_id,
            state.outgoing_email.casefold(),
            state.outgoing_user_id,
            state.membership_epoch,
            state.member_switch_run_id,
            state.start_command_id,
        )
        actual = (
            stored.evaluation_id,
            stored.workspace_id,
            stored.workspace_account_id,
            stored.outgoing_account_id,
            stored.outgoing_email.casefold(),
            stored.outgoing_user_id,
            stored.membership_epoch,
            stored.member_switch_run_id,
            stored.start_command_id,
        )
        if actual != expected or (
            stored.quota_operation_id is not None
            and state.quota_operation_id is not None
            and stored.quota_operation_id != state.quota_operation_id
        ):
            raise ControlConflict("rotation_evaluation_identity_mismatch")
        return existing, stored

    async def _quota_request(self, operation_id: str, effect: RotationEffect) -> None:
        async with self._quota_sessions() as session:
            repository = RotationQuotaRepository(session, clock=self._clock)
            await repository.record_effect_request(operation_id, effect=effect)

    async def _quota_preflight(self, operation_id: str, effect: RotationEffect) -> None:
        async with self._quota_sessions() as session:
            repository = RotationQuotaRepository(session, clock=self._clock)
            await repository.require_effect_request_open(operation_id, effect=effect)

    async def _quota_outcome(
        self,
        operation_id: str,
        effect: RotationEffect,
        outcome: RotationEffectOutcome,
    ) -> None:
        async with self._quota_sessions() as session:
            repository = RotationQuotaRepository(session, clock=self._clock)
            await repository.record_effect_outcome(operation_id, effect=effect, outcome=outcome)

    async def _release_quota(self, operation_id: str | None) -> None:
        if operation_id is None:
            return
        async with self._quota_sessions() as session:
            repository = RotationQuotaRepository(session, clock=self._clock)
            await repository.release_reservation(operation_id)

    async def _complete_quota(self, operation_id: str) -> None:
        async with self._quota_sessions() as session:
            repository = RotationQuotaRepository(session, clock=self._clock)
            await repository.mark_completed(operation_id)

    async def _terminal_before_effect(
        self,
        record: ControlRecord,
        state: RotationControllerState,
        *,
        code: str,
        attention: bool,
    ) -> RotationControllerState:
        await self._release_quota(state.quota_operation_id)
        _, state = await self._persist(
            record,
            state.model_copy(
                update={
                    "phase": "needs_attention" if attention else "completed",
                    "last_code": code,
                    "terminal_reason": code,
                }
            ),
        )
        return state

    async def _retain_attention(
        self,
        record: ControlRecord,
        state: RotationControllerState,
        *,
        code: str,
    ) -> RotationControllerState:
        """Retain quota/effect ownership when a durable child may already have crossed."""
        _, state = await self._persist(
            record,
            state.model_copy(
                update={
                    "phase": "needs_attention",
                    "last_code": code,
                    "terminal_reason": code,
                }
            ),
        )
        return state

    async def _terminal_after_preeffect_cleanup(
        self,
        record: ControlRecord,
        state: RotationControllerState,
        run,
        *,
        code: str,
        attention: bool,
    ) -> RotationControllerState:
        if not await self._cancel_preeffect_run(state, run):
            return await self._retain_attention(
                record,
                state,
                code=f"{code}:preeffect_cleanup_unresolved",
            )
        return await self._terminal_before_effect(record, state, code=code, attention=attention)

    async def _settle_start_non_effect(
        self,
        record: ControlRecord,
        state: RotationControllerState,
        run,
    ) -> RotationControllerState:
        """Close a claimed start whose durable result proves no operation began."""
        operation_id = state.quota_operation_id
        if operation_id is None:
            return await self._retain_attention(record, state, code="rotation_quota_evidence_missing")
        try:
            await self._quota_request(operation_id, "remove")
            await self._quota_outcome(operation_id, "remove", "authoritative_non_effect")
        except ValueError as exc:
            return await self._retain_attention(
                record,
                state,
                code=f"rotation_remove_accounting_failed:{exc}",
            )

        state = state.model_copy(
            update={
                "remove_state": "authoritative_non_effect",
                "member_switch_operation_id": None,
                "phase": "finalizing",
                "last_code": run.last_code,
                "terminal_reason": None,
            }
        )
        record, state = await self._persist(record, state)
        try:
            finalized = await self.member_switch.finalize_rotation_non_effect(
                state.member_switch_run_id,
                rotation_controller_id=state.id,
            )
        except ControlConflict as exc:
            return await self._retain_attention(record, state, code=f"rotation_non_effect_finalize_failed:{exc.code}")

        if finalized.phase != "completed":
            _, state = await self._persist(
                record,
                state.model_copy(update={"phase": "finalizing", "last_code": finalized.last_code}),
            )
            return state
        await self._release_quota(operation_id)
        _, state = await self._persist(
            record,
            state.model_copy(
                update={
                    "phase": "completed",
                    "last_code": f"rotation_start_non_effect:{run.last_code}",
                    "terminal_reason": run.last_code,
                }
            ),
        )
        return state

    async def _start_child(
        self,
        record: ControlRecord,
        state: RotationControllerState,
        run,
    ) -> RotationControllerState:
        child = await self.controls.get(state.member_switch_run_id)
        effect_claimed = self._start_claimed(child, state, run)
        if (
            state.foundation_state != RotationFoundationState.ADMISSION_READY.value
            or not state.snapshot_committed
            or not self._p4_qualified(state)
            or state.quota_operation_id is None
            or state.incoming is None
        ):
            code = "rotation_pre_effect_evidence_incomplete"
            if effect_claimed:
                return await self._retain_attention(record, state, code=code)
            return await self._terminal_after_preeffect_cleanup(record, state, run, code=code, attention=True)

        if (
            run.identity != state.incoming
            or run.removed_email is None
            or run.removed_email.casefold() != state.outgoing_email
        ):
            code = "rotation_preview_identity_mismatch"
            if effect_claimed:
                return await self._retain_attention(record, state, code=code)
            return await self._terminal_after_preeffect_cleanup(record, state, run, code=code, attention=True)
        if not effect_claimed and (run.phase != "previewed" or "start" not in run.allowed_actions):
            return await self._terminal_after_preeffect_cleanup(
                record,
                state,
                run,
                code=f"rotation_preview_not_ready:{run.last_code}",
                attention=True,
            )

        quota_operation_id = state.quota_operation_id
        if effect_claimed:
            # The durable child is the sole authority for whether ``start`` may
            # have crossed.  If restart observes that claim before the
            # controller published its accounting state, backfill P3 and then
            # reconcile only; never issue another start.
            try:
                await self._quota_request(quota_operation_id, "remove")
            except ValueError as exc:
                return await self._retain_attention(
                    record,
                    state,
                    code=f"rotation_remove_accounting_failed:{exc}",
                )
            record, state = await self._persist(
                record,
                state.model_copy(
                    update={
                        "remove_state": "unknown",
                        "phase": "removal_effect_unknown" if run.pending_action == "start" else "removing",
                        "last_code": run.last_code,
                    }
                ),
            )
            if run.phase == "failed" and not run.operation_id and not run.pending_action:
                return await self._settle_start_non_effect(record, state, run)
            return await self.resume(state.id)

        try:
            await self._quota_preflight(quota_operation_id, "remove")
        except ValueError as exc:
            return await self._terminal_after_preeffect_cleanup(
                record,
                state,
                run,
                code=f"rotation_remove_preflight_failed:{exc}",
                attention=True,
            )
        try:
            # The child command claims the durable start intent BEFORE any
            # external Companion mutation.  Controller/P3 accounting follows
            # that claim and can be reconstructed from it after a crash.
            run = await self.member_switch.command_rotation(
                state.member_switch_run_id,
                CommandRequest(
                    command_id=UUID(state.start_command_id),
                    expected_revision=run.revision,
                    action="start",
                ),
                rotation_controller_id=state.id,
                pre_effect=lambda: self._quota_request(quota_operation_id, "remove"),
            )
        except ControlConflict as exc:
            child = await self.controls.get(state.member_switch_run_id)
            latest = await self.member_switch.get(state.member_switch_run_id)
            if self._start_claimed(child, state, latest):
                try:
                    await self._quota_request(quota_operation_id, "remove")
                except ValueError as accounting_exc:
                    return await self._retain_attention(
                        record,
                        state,
                        code=f"rotation_remove_accounting_failed:{accounting_exc}",
                    )
                record, state = await self._persist(
                    record,
                    state.model_copy(
                        update={
                            "remove_state": "unknown",
                            "phase": "removal_effect_unknown",
                            "last_code": exc.code,
                            "terminal_reason": None,
                        }
                    ),
                )
                return await self.resume(state.id)
            # Either start preconditions rejected before the claim, or the
            # post-claim/pre-Companion accounting hook proved a local
            # non-effect.  Confirm the child scope is closed before returning
            # quota; a concurrent winning claim must keep both retained.
            return await self._terminal_after_preeffect_cleanup(
                record,
                state,
                latest or run,
                code=f"rotation_start_rejected:{exc.code}",
                attention=True,
            )

        record, state = await self._persist(
            record,
            state.model_copy(
                update={
                    "remove_state": "unknown",
                    "member_switch_operation_id": run.operation_id,
                    "phase": "removing" if run.operation_id else "removal_effect_unknown",
                    "last_code": run.last_code,
                }
            ),
        )
        if run.phase == "failed" and not run.operation_id and not run.pending_action:
            return await self._settle_start_non_effect(record, state, run)
        return await self.resume(state.id)

    async def evaluate_and_start(
        self,
        *,
        weekly: RotationWeeklyEvidence,
        reset: RotationResetEvidence | None,
        quota: RotationQuotaReservationEvidence | None,
        current_member: UsageAccountIdentity,
        final_usage_receipt: RotationUsageObservation | None,
        membership_epoch: str,
        p4_provenance: CompanionTypedTelemetryProvenance | None,
    ) -> RotationControllerState:
        evaluation = weekly.evaluation
        now = _utc(self._clock())
        decision_weekly = weekly
        if final_usage_receipt is not None:
            prior_provenance = weekly.observation.provenance
            final_not_before = weekly.not_before
            if prior_provenance is not None:
                prior_started = _utc(prior_provenance.started_at)
                final_not_before = (
                    prior_started if final_not_before is None else max(_utc(final_not_before), prior_started)
                )
            # The removal snapshot is the latest same-fetch 5H+Weekly evidence
            # when present.  Re-assess its Weekly window at the effect boundary
            # so a newly recovered account can never be removed using an older
            # exhausted observation/quota reservation.
            decision_weekly = bind_rotation_weekly_evidence(
                final_usage_receipt,
                evaluation,
                not_before=final_not_before,
            )
        decision_assessment = decision_weekly.assess(current_member, now=now)
        foundation = evaluate_rotation_foundation(
            decision_weekly,
            current_member=current_member,
            now=now,
            reset=reset,
            # A previously reserved slot cannot turn a newly available Weekly
            # window into invalid evidence.  Recovered/available usage closes
            # this evaluation before effect and the reservation is returned.
            quota=quota if decision_assessment.state == "exhausted" else None,
        )
        provenance = decision_weekly.observation.provenance
        initial = RotationControllerState(
            id=rotation_controller_id(evaluation.evaluation_id),
            evaluation_id=evaluation.evaluation_id,
            workspace_id=evaluation.workspace_id,
            workspace_account_id=evaluation.workspace_account_id,
            outgoing_account_id=evaluation.member.account_id,
            outgoing_email=evaluation.member.email.casefold(),
            outgoing_user_id=evaluation.member.user_id or "",
            foundation_state=foundation.state.value,
            foundation_evidence_ref=provenance.fetch_id if provenance is not None else None,
            foundation_admission_ready=foundation.admission_ready,
            foundation_attention_required=foundation.attention_required,
            foundation_weekly_state=cast(
                Literal["unknown", "available", "exhausted"],
                foundation.weekly_state,
            ),
            foundation_weekly_reason=foundation.weekly_reason,
            reset_status=foundation.reset_status,
            foundation_quota_code=foundation.quota_code,
            foundation_count_24h=foundation.count_24h,
            foundation_count_168h=foundation.count_168h,
            quota_operation_id=(quota.operation_id if quota is not None and quota.evaluation == evaluation else None),
            membership_epoch=membership_epoch,
            p4_provenance=p4_provenance,
            p4_provenance_verified=bool(p4_provenance and p4_provenance.qualified),
            member_switch_run_id=rotation_run_id(evaluation.evaluation_id),
            start_command_id=rotation_start_command_id(evaluation.evaluation_id),
            last_code=foundation.state.value,
            updated_at=now,
        )
        record, state = await self._create_or_load(initial)
        if state.phase in {"completed", "needs_attention"}:
            return await self.resume(state.id)
        child = await self.controls.get(state.member_switch_run_id)
        run = await self.member_switch.get(state.member_switch_run_id) if child is not None else None
        if state.remove_state != "not_attempted" or self._start_claimed(child, state, run):
            return await self.resume(state.id)

        # The G1 contract is the only membership-admission fact source.
        if foundation.state is not RotationFoundationState.ADMISSION_READY or not foundation.admission_ready:
            if run is not None:
                return await self._terminal_after_preeffect_cleanup(
                    record,
                    state.model_copy(
                        update={
                            **self._foundation_fields(foundation),
                            "last_code": foundation.state.value,
                        }
                    ),
                    run,
                    code=foundation.state.value,
                    attention=foundation.attention_required,
                )
            return await self._terminal_before_effect(
                record,
                state.model_copy(
                    update={
                        **self._foundation_fields(foundation),
                        "last_code": foundation.state.value,
                    }
                ),
                code=foundation.state.value,
                attention=foundation.attention_required,
            )
        if quota is None or state.quota_operation_id is None:
            return await self._terminal_before_effect(
                record, state, code="rotation_quota_evidence_missing", attention=True
            )
        if p4_provenance is None or not p4_provenance.qualified:
            if run is not None:
                return await self._terminal_after_preeffect_cleanup(
                    record,
                    state.model_copy(update={"p4_provenance": p4_provenance, "p4_provenance_verified": False}),
                    run,
                    code="rotation_p4_provenance_unverified",
                    attention=True,
                )
            return await self._terminal_before_effect(
                record,
                state.model_copy(update={"p4_provenance": p4_provenance, "p4_provenance_verified": False}),
                code="rotation_p4_provenance_unverified",
                attention=True,
            )
        if not state.snapshot_committed and final_usage_receipt is None:
            return await self._terminal_before_effect(
                record, state, code="rotation_final_usage_missing", attention=True
            )

        admission = await local_admission(
            self.controls,
            owning_run_id=state.member_switch_run_id if run is not None else None,
        )
        if not admission.can_create:
            return await self._terminal_before_effect(
                record,
                state,
                code=f"rotation_member_switch_blocked:{admission.blockers[0].code}",
                attention=True,
            )

        if run is not None:
            if state.incoming is None or state.outgoing_preset_id is None:
                return await self._terminal_before_effect(
                    record,
                    state,
                    code="rotation_persisted_candidate_missing",
                    attention=True,
                )
            incoming = state.incoming
            outgoing_preset_id = state.outgoing_preset_id
        else:
            try:
                catalog = await self.member_switch.refresh_catalog()
                workspace = next(
                    (
                        item
                        for item in catalog.workspaces
                        if item.id == evaluation.workspace_id
                        and item.workspace_account_id == evaluation.workspace_account_id
                    ),
                    None,
                )
                if workspace is None:
                    raise ControlConflict("rotation_workspace_identity_mismatch")
                outgoing_preset_id, candidate = select_rotation_candidate(workspace, outgoing=evaluation.member)
            except ControlConflict as exc:
                return await self._terminal_before_effect(record, state, code=exc.code, attention=True)

            incoming = Identity(
                workspace_id=workspace.id,
                workspace_account_id=workspace.workspace_account_id,
                preset_id=candidate.preset_id,
                target_email=candidate.email.casefold(),
                target_user_id=candidate.user_id,
                catalog_fingerprint=catalog.catalog_fingerprint,
            )
        if state.incoming is not None and state.incoming != incoming:
            if run is not None:
                return await self._terminal_after_preeffect_cleanup(
                    record,
                    state,
                    run,
                    code="rotation_candidate_identity_changed",
                    attention=True,
                )
            return await self._terminal_before_effect(
                record,
                state,
                code="rotation_candidate_identity_changed",
                attention=True,
            )
        record, state = await self._persist(
            record,
            state.model_copy(
                update={
                    **self._foundation_fields(foundation),
                    "foundation_evidence_ref": provenance.fetch_id if provenance is not None else None,
                    "outgoing_preset_id": outgoing_preset_id,
                    "incoming": incoming,
                    "p4_provenance": p4_provenance,
                    "p4_provenance_verified": p4_provenance.qualified,
                    "phase": "snapshotting_outgoing",
                    "last_code": (
                        "rotation_snapshot_committed" if state.snapshot_committed else "rotation_snapshot_required"
                    ),
                }
            ),
        )
        if state.phase != "snapshotting_outgoing" or state.incoming != incoming:
            return state

        if not state.snapshot_committed:
            assert final_usage_receipt is not None
            try:
                async with self._snapshot_sessions() as session:
                    repository = MemberUsageSnapshotRepository(session, clock=self._clock)
                    snapshots = await repository.recover_final_snapshot_epoch(
                        workspace_id=evaluation.workspace_id,
                        workspace_account_id=evaluation.workspace_account_id,
                        account_id=evaluation.member.account_id,
                        preset_id=outgoing_preset_id,
                        email=evaluation.member.email,
                        user_id=evaluation.member.user_id or "",
                        membership_epoch=membership_epoch,
                    )
                    if snapshots is None:
                        snapshot_inputs = final_usage_snapshot_inputs(
                            final_usage_receipt,
                            evaluation,
                            current_member,
                            now=_utc(self._clock()),
                        )
                        snapshots = await repository.retain_final_snapshots(
                            workspace_id=evaluation.workspace_id,
                            workspace_account_id=evaluation.workspace_account_id,
                            account_id=evaluation.member.account_id,
                            preset_id=outgoing_preset_id,
                            email=evaluation.member.email,
                            user_id=evaluation.member.user_id or "",
                            membership_epoch=membership_epoch,
                            observations=snapshot_inputs,
                        )
            except (FinalUsageRetentionUnavailable, HistoricalUsageConflict, ValueError) as exc:
                code = getattr(exc, "code", None) or str(exc) or "rotation_snapshot_failed"
                return await self._terminal_before_effect(
                    record, state, code=f"rotation_snapshot_failed:{code}", attention=True
                )

            record, state = await self._persist(
                record,
                state.model_copy(
                    update={
                        "snapshot_committed": True,
                        "final_snapshot_ids": [item.id for item in snapshots],
                        "last_code": "rotation_snapshot_committed",
                    }
                ),
            )
        if not state.snapshot_committed:
            return state

        if run is None:
            request = CreateRunRequest(
                run_id=UUID(state.member_switch_run_id),
                workspace_id=state.workspace_id,
                preset_id=incoming.preset_id,
                catalog_fingerprint=incoming.catalog_fingerprint,
            )
            try:
                run = await self.member_switch.create_rotation_run(request, rotation_controller_id=state.id)
            except ControlConflict as exc:
                existing_child = await self.controls.get(state.member_switch_run_id)
                if existing_child is None:
                    return await self._terminal_before_effect(
                        record, state, code=f"rotation_child_run_blocked:{exc.code}", attention=True
                    )
                try:
                    run = self.member_switch._view(existing_child)
                except ControlConflict:
                    return await self._terminal_before_effect(
                        record, state, code="rotation_child_run_identity_mismatch", attention=True
                    )

        return await self._start_child(record, state, run)

    async def _cancel_preeffect_run(self, state: RotationControllerState, run) -> bool:
        if run.phase == "completed" and run.pending_action is None:
            return True
        try:
            if (
                run.phase == "failed"
                and run.pending_action is None
                and run.operation_id is None
                and run.handoff_id is None
                and run.browser_operation_id is None
            ):
                closed = await self.member_switch.finalize_rotation_non_effect(
                    state.member_switch_run_id,
                    rotation_controller_id=state.id,
                )
                return closed.phase == "completed"
            if "cancel" not in run.allowed_actions:
                return False
            command_id = UUID(_stable_uuid("cancel", state.evaluation_id))
            closed = await self.member_switch.command_rotation(
                state.member_switch_run_id,
                CommandRequest(command_id=command_id, expected_revision=run.revision, action="cancel"),
                rotation_controller_id=state.id,
            )
            return closed.phase == "completed" and closed.pending_action is None
        except ControlConflict:
            latest = await self.member_switch.get(state.member_switch_run_id)
            return bool(latest is not None and latest.phase == "completed" and latest.pending_action is None)

    async def _reconcile_child(self, state: RotationControllerState, run):
        if run.pending_action:
            try:
                return await self.member_switch.command_rotation(
                    state.member_switch_run_id,
                    CommandRequest(
                        command_id=UUID(_stable_uuid("reconcile", state.evaluation_id, str(run.revision))),
                        expected_revision=run.revision,
                        action="reconcile",
                    ),
                    rotation_controller_id=state.id,
                )
            except ControlConflict:
                return run
        if run.operation_id:
            try:
                return await self.member_switch.command_rotation(
                    state.member_switch_run_id,
                    CommandRequest(
                        command_id=UUID(_stable_uuid("observe", state.evaluation_id, str(run.revision))),
                        expected_revision=run.revision,
                        action="observe_membership",
                    ),
                    rotation_controller_id=state.id,
                )
            except ControlConflict:
                latest = await self.member_switch.get(state.member_switch_run_id)
                return latest or run
        return run

    async def resume(self, controller_id: str) -> RotationControllerState:
        record = await self.controls.get(controller_id)
        if record is None:
            raise ControlConflict("rotation_controller_not_found")
        state = self._decode(record)
        run = await self.member_switch.get(state.member_switch_run_id)

        # A prior process may have terminalized the controller after the child
        # durably claimed ``finish`` but before its release receipt settled.  A
        # terminal controller must not make that owned cleanup unrecoverable.
        if state.phase in {"completed", "needs_attention"}:
            if run is None or run.pending_action != "finish":
                return state
            reconciled = await self._reconcile_child(state, run)
            if reconciled.pending_action:
                _, state = await self._persist(
                    record,
                    state.model_copy(update={"phase": "finalizing", "last_code": reconciled.last_code}),
                )
                return state
            if reconciled.phase == "completed":
                if state.remove_state == "authoritative_non_effect":
                    await self._release_quota(state.quota_operation_id)
                elif state.remove_state == "confirmed" and state.invite_state == "confirmed":
                    try:
                        await self._complete_quota(state.quota_operation_id or "")
                    except ValueError as exc:
                        return await self._retain_attention(
                            record,
                            state,
                            code=f"rotation_quota_completion_failed:{exc}",
                        )
                _, state = await self._persist(
                    record,
                    state.model_copy(
                        update={
                            "phase": "completed",
                            "last_code": "rotation_completed",
                            "terminal_reason": None,
                        }
                    ),
                )
            return state

        if state.remove_state == "not_attempted":
            if run is None:
                # Snapshot publication is durable, but it is not authority to
                # start later.  A new scheduler evaluation must bring fresh G1
                # facts; evaluate_and_start will reuse the immutable snapshot.
                if state.snapshot_committed:
                    _, state = await self._persist(
                        record,
                        state.model_copy(
                            update={
                                "phase": "foundation_evaluating",
                                "last_code": "rotation_fresh_evaluation_required",
                                "terminal_reason": None,
                            }
                        ),
                    )
                return state
            child = await self.controls.get(state.member_switch_run_id)
            if not self._start_claimed(child, state, run):
                # Never cross a fresh external-effect boundary from resume()
                # using stored foundation/P4 facts.  The next evaluate call must
                # re-assess current member, Weekly freshness, reset and quota.
                _, state = await self._persist(
                    record,
                    state.model_copy(
                        update={
                            "phase": "foundation_evaluating",
                            "last_code": "rotation_fresh_evaluation_required",
                            "terminal_reason": None,
                        }
                    ),
                )
                return state
            try:
                await self._quota_request(state.quota_operation_id or "", "remove")
            except ValueError as exc:
                return await self._retain_attention(
                    record,
                    state,
                    code=f"rotation_remove_accounting_failed:{exc}",
                )
            record, state = await self._persist(
                record,
                state.model_copy(
                    update={
                        "remove_state": "unknown",
                        "phase": "removal_effect_unknown" if run.pending_action == "start" else "removing",
                        "last_code": run.last_code,
                        "terminal_reason": None,
                    }
                ),
            )
            if run.phase == "failed" and not run.operation_id and not run.pending_action:
                return await self._settle_start_non_effect(record, state, run)
        if run is None:
            _, state = await self._persist(
                record,
                state.model_copy(
                    update={
                        "phase": "needs_attention",
                        "last_code": "rotation_effect_owner_missing",
                        "terminal_reason": "rotation_effect_owner_missing",
                    }
                ),
            )
            return state

        run = await self._reconcile_child(state, run)
        if run.pending_action:
            phase = (
                "removal_effect_unknown"
                if run.pending_action == "start"
                else "finalizing"
                if run.pending_action == "finish"
                else state.phase
            )
            _, state = await self._persist(
                record,
                state.model_copy(update={"phase": phase, "last_code": run.last_code}),
            )
            return state
        if not run.operation_id or run.operation is None:
            if run.phase == "failed":
                return await self._settle_start_non_effect(record, state, run)
            if run.phase == "completed" and state.remove_state == "authoritative_non_effect":
                await self._release_quota(state.quota_operation_id)
                _, state = await self._persist(
                    record,
                    state.model_copy(
                        update={
                            "phase": "completed",
                            "last_code": "rotation_start_non_effect",
                            "terminal_reason": run.last_code,
                        }
                    ),
                )
                return state
            _, state = await self._persist(
                record,
                state.model_copy(
                    update={
                        "phase": "removal_effect_unknown",
                        "last_code": run.last_code,
                    }
                ),
            )
            return state

        operation = run.operation
        settlement = operation.invitation_settlement
        invite_observation = settlement.invite_response_observation if settlement is not None else None
        updates: dict[str, object] = {
            "member_switch_operation_id": operation.operation_id,
            "invite_response_observation": invite_observation,
            "last_code": operation.code,
        }

        if pre_membership_failure_confirmed(operation):
            if state.remove_state == "unknown":
                await self._quota_outcome(state.quota_operation_id or "", "remove", "authoritative_non_effect")
            updates.update(
                remove_state="authoritative_non_effect",
                phase="finalizing",
                terminal_reason=None,
            )
            if "finish" in run.allowed_actions:
                try:
                    run = await self.member_switch.command_rotation(
                        state.member_switch_run_id,
                        CommandRequest(
                            command_id=UUID(_stable_uuid("preeffect-finish", state.evaluation_id)),
                            expected_revision=run.revision,
                            action="finish",
                        ),
                        rotation_controller_id=state.id,
                    )
                except ControlConflict as exc:
                    latest = await self.member_switch.get(state.member_switch_run_id)
                    if latest is not None:
                        run = latest
                    updates.update(phase="finalizing", last_code=exc.code)
            await self._release_quota(state.quota_operation_id)
            if run.phase == "completed" and not run.pending_action:
                updates.update(
                    phase="completed",
                    last_code=f"rotation_pre_membership_non_effect:{operation.code}",
                    terminal_reason=operation.code,
                )
            _, state = await self._persist(
                record,
                state.model_copy(update=updates),
            )
            return state

        removed_exact = (
            operation.removed_email is not None
            and operation.removed_user_id is not None
            and operation.removed_email.casefold() == state.outgoing_email.casefold()
            and operation.removed_user_id == state.outgoing_user_id
        )
        if removed_exact and state.remove_state == "unknown":
            await self._quota_outcome(state.quota_operation_id or "", "remove", "confirmed")
            state = state.model_copy(update={"remove_state": "confirmed"})
            updates["remove_state"] = "confirmed"
            updates["phase"] = "removal_confirmed"
        elif state.remove_state == "unknown":
            updates["phase"] = "removal_effect_unknown"

        if settlement is not None and settlement.invitation_attempted:
            if not removed_exact:
                _, state = await self._persist(
                    record,
                    state.model_copy(
                        update={
                            **updates,
                            "phase": "needs_attention",
                            "terminal_reason": "rotation_invite_without_exact_removal_identity",
                        }
                    ),
                )
                return state
            if state.invite_state == "not_attempted":
                await self._quota_request(state.quota_operation_id or "", "invite")
                state = state.model_copy(update={"invite_state": "unknown"})
                updates["invite_state"] = "unknown"
                updates["phase"] = "inviting"
            if settlement.invitation_non_effect_confirmed:
                if state.invite_state == "unknown":
                    await self._quota_outcome(state.quota_operation_id or "", "invite", "authoritative_non_effect")
                updates.update(
                    invite_state="authoritative_non_effect",
                    phase="needs_attention",
                    terminal_reason="rotation_invite_non_effect_confirmed",
                )
            elif settlement.invitation_issued:
                if state.invite_state == "unknown":
                    await self._quota_outcome(state.quota_operation_id or "", "invite", "confirmed")
                updates.update(invite_state="confirmed", phase="invite_sent")
            else:
                updates["phase"] = "invite_effect_unknown"

        if _response_capture_failed(invite_observation):
            assert invite_observation is not None
            updates.update(
                phase="needs_attention",
                terminal_reason=f"rotation_invite_telemetry_{invite_observation.capture_state}",
            )

        effective_remove = updates.get("remove_state", state.remove_state)
        effective_invite = updates.get("invite_state", state.invite_state)
        membership_settled = (
            membership_confirmed(operation) and settlement is not None and settlement.final_membership_confirmed
        )
        if membership_settled:
            if effective_remove != "confirmed" or effective_invite != "confirmed":
                updates.update(
                    phase="needs_attention",
                    terminal_reason="rotation_membership_effect_evidence_incomplete",
                )
            elif updates.get("phase") != "needs_attention":
                try:
                    finalized = await self.member_switch.finalize_rotation_membership(
                        state.member_switch_run_id,
                        rotation_controller_id=state.id,
                        command_id=_stable_uuid("membership-finish", state.evaluation_id),
                    )
                except ControlConflict as exc:
                    # ``finish`` is itself durable.  Keep the controller
                    # resumable so a later read-only reconciliation can settle
                    # operation_release_pending/operation_finalized.
                    updates.update(
                        phase="finalizing",
                        last_code=f"rotation_finalize_pending:{exc.code}",
                        terminal_reason=None,
                    )
                else:
                    if finalized.phase == "completed":
                        try:
                            await self._complete_quota(state.quota_operation_id or "")
                        except ValueError as exc:
                            updates.update(
                                phase="needs_attention",
                                terminal_reason=f"rotation_quota_completion_failed:{exc}",
                            )
                        else:
                            updates.update(
                                phase="completed",
                                last_code="rotation_completed",
                                terminal_reason=None,
                            )
                    else:
                        updates.update(phase="finalizing", last_code=finalized.last_code)
        elif effective_invite == "confirmed" and updates.get("phase") != "needs_attention":
            updates["phase"] = "waiting_membership"
        elif operation.stage == "needs_attention" or operation.code == "operation_outcome_unknown":
            updates.update(phase="needs_attention", terminal_reason=operation.code)
        elif operation.stage == "failed" and effective_remove != "authoritative_non_effect":
            updates.update(phase="needs_attention", terminal_reason=operation.code)

        _, state = await self._persist(record, state.model_copy(update=updates))
        return state
