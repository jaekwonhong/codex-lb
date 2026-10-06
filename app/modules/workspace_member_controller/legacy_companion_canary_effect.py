from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from app.modules.member_switch.companion import CompanionPort
from app.modules.member_switch.policy import membership_confirmed, pre_membership_failure_confirmed
from app.modules.member_switch.schemas import (
    EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY,
    OWNER_MEMBERSHIP_MUTATION_CAPABILITY,
    OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY,
    RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY,
    StartRequest,
)
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationCommand,
    MembershipMutationOutcome,
    MembershipMutationReceipt,
    MembershipMutationSpec,
)
from app.modules.workspace_member_controller.mutation_ports import MembershipMutationEffectPort

_CANARY_EFFECT_CAPABILITY = "member_rotation_canary_effect_gate_v1"
_CANARY_ROLLBACK_CAPABILITY = "member_rotation_canary_rollback_binding_v1"
_REMOVE_TELEMETRY_CAPABILITY = "member_rotation_managed_remove_telemetry_v1"
CANARY_REQUIRED_CAPABILITIES = frozenset(
    {
        EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY,
        OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY,
        OWNER_MEMBERSHIP_MUTATION_CAPABILITY,
        RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY,
        _CANARY_EFFECT_CAPABILITY,
        _CANARY_ROLLBACK_CAPABILITY,
        _REMOVE_TELEMETRY_CAPABILITY,
        "durable_client_flow",
        "durable_participant_commands_v1",
    }
)
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


class LegacyCompanionCanarySwitchEffect(MembershipMutationEffectPort):
    """Canary-only switch adapter over the already-qualified Companion protocol.

    It never falls back from `/canary-operations` to the normal operation path.
    Reconciliation is observational and never resends the start mutation.
    """

    def __init__(
        self,
        companion: CompanionPort,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        settle_timeout_seconds: float = 190.0,
        poll_interval_seconds: float = 2.0,
        canary_purpose: Literal["forward", "rollback"] = "forward",
        canary_parent_client_flow_id: str | None = None,
    ) -> None:
        if canary_purpose not in {"forward", "rollback"}:
            raise ValueError("canary_purpose_invalid")
        if canary_purpose == "forward" and canary_parent_client_flow_id is not None:
            raise ValueError("canary_forward_parent_forbidden")
        if canary_purpose == "rollback" and not canary_parent_client_flow_id:
            raise ValueError("canary_rollback_parent_required")
        if canary_parent_client_flow_id is not None:
            try:
                UUID(canary_parent_client_flow_id)
            except ValueError as exc:
                raise ValueError("canary_parent_client_flow_invalid") from exc
        self._companion = companion
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or asyncio.sleep
        self._settle_timeout_seconds = settle_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._canary_purpose = canary_purpose
        self._canary_parent_client_flow_id = canary_parent_client_flow_id

    async def execute(self, command: MembershipMutationCommand) -> MembershipMutationReceipt:
        mutation = command.mutation
        if mutation.action != "switch" or mutation.incoming is None or mutation.outgoing is None:
            return self._receipt(
                operation_id=str(command.operation_id),
                command_id=str(command.command_id),
                request_fingerprint=command.fingerprint(),
                mutation=mutation,
                outcome="authoritative_non_effect",
                code="canary_switch_action_required",
                non_effect=True,
            )

        catalog = await self._companion.catalog()
        if (
            not catalog.enabled
            or catalog.catalog_fingerprint != mutation.catalog_fingerprint
            or not CANARY_REQUIRED_CAPABILITIES.issubset(catalog.capabilities)
        ):
            return self._receipt(
                operation_id=str(command.operation_id),
                command_id=str(command.command_id),
                request_fingerprint=command.fingerprint(),
                mutation=mutation,
                outcome="authoritative_non_effect",
                code="canary_catalog_not_qualified",
                non_effect=True,
            )
        workspaces = [
            workspace
            for workspace in catalog.workspaces
            if workspace.id == mutation.workspace_id
            and workspace.workspace_account_id == mutation.workspace_account_id
        ]
        if len(workspaces) != 1:
            return self._local_non_effect(command, "canary_workspace_identity_mismatch")
        workspace = workspaces[0]
        incoming = [
            member
            for member in workspace.members
            if member.preset_id == mutation.incoming.preset_id
            and member.email.casefold() == mutation.incoming.email.casefold()
            and member.user_id == mutation.incoming.user_id
        ]
        if len(incoming) != 1:
            return self._local_non_effect(command, "canary_incoming_identity_mismatch")

        admission = await self._companion.admission()
        if not admission.can_start:
            return self._local_non_effect(command, f"canary_companion_not_idle:{admission.code}")

        from app.modules.member_switch.schemas import PreviewRequest

        preview = await self._companion.preview(
            PreviewRequest(
                workspace_account_id=mutation.workspace_account_id,
                preset_id=incoming[0].preset_id,
                catalog_fingerprint=mutation.catalog_fingerprint,
            )
        )
        if (
            not preview.ready
            or not preview.preview_token
            or preview.expires_at is None
            or preview.expires_at <= self._clock()
        ):
            return self._local_non_effect(command, f"canary_preview_not_ready:{preview.code}")
        if (
            preview.target_email is None
            or preview.remove_email is None
            or preview.target_email.casefold() != mutation.incoming.email.casefold()
            or preview.remove_email.casefold() != mutation.outgoing.email.casefold()
        ):
            return self._local_non_effect(command, "canary_preview_identity_mismatch")

        receipt = await self._companion.start(
            StartRequest(
                preview_token=preview.preview_token,
                client_flow_id=str(command.operation_id),
                canary=True,
                canary_purpose=self._canary_purpose,
                canary_parent_client_flow_id=self._canary_parent_client_flow_id,
            )
        )
        if not receipt.accepted:
            if receipt.operation_id is not None:
                return self._unknown(command, "canary_start_receipt_invalid")
            return self._local_non_effect(command, f"canary_start_non_effect:{receipt.code}")
        if not receipt.operation_id:
            return self._unknown(command, "canary_start_receipt_invalid")
        return await self._settle(
            operation_id=receipt.operation_id,
            command_operation_id=str(command.operation_id),
            command_id=str(command.command_id),
            request_fingerprint=command.fingerprint(),
            mutation=mutation,
        )

    async def reconcile(
        self,
        *,
        operation_id: str,
        command_id: str,
        request_fingerprint: str,
        mutation: MembershipMutationSpec,
    ) -> MembershipMutationReceipt | None:
        start = await self._companion.lookup(operation_id)
        if start is None:
            return None
        if not start.accepted:
            if start.operation_id is not None:
                return self._receipt(
                    operation_id=operation_id,
                    command_id=command_id,
                    request_fingerprint=request_fingerprint,
                    mutation=mutation,
                    outcome="outcome_unknown",
                    code="canary_reconcile_start_invalid",
                )
            return self._receipt(
                operation_id=operation_id,
                command_id=command_id,
                request_fingerprint=request_fingerprint,
                mutation=mutation,
                outcome="authoritative_non_effect",
                code=f"canary_start_non_effect:{start.code}",
                non_effect=True,
            )
        if not start.operation_id:
            return self._receipt(
                operation_id=operation_id,
                command_id=command_id,
                request_fingerprint=request_fingerprint,
                mutation=mutation,
                outcome="outcome_unknown",
                code="canary_reconcile_start_invalid",
            )
        return await self._settle(
            operation_id=start.operation_id,
            command_operation_id=operation_id,
            command_id=command_id,
            request_fingerprint=request_fingerprint,
            mutation=mutation,
        )

    async def _settle(
        self,
        *,
        operation_id: str,
        command_operation_id: str,
        command_id: str,
        request_fingerprint: str,
        mutation: MembershipMutationSpec,
    ) -> MembershipMutationReceipt:
        incoming = mutation.incoming
        outgoing = mutation.outgoing
        if incoming is None or outgoing is None:
            return self._receipt(
                operation_id=command_operation_id,
                command_id=command_id,
                request_fingerprint=request_fingerprint,
                mutation=mutation,
                outcome="authoritative_non_effect",
                code="canary_switch_identity_missing",
                non_effect=True,
            )
        deadline = asyncio.get_running_loop().time() + self._settle_timeout_seconds
        while True:
            operation = await self._companion.operation(operation_id)
            if (
                operation.operation_id != operation_id
                or operation.member_switch_operation_id != operation_id
                or operation.workspace_id != mutation.workspace_id
                or operation.workspace_account_id != mutation.workspace_account_id
                or operation.target_email.casefold() != incoming.email.casefold()
                or operation.target_user_id != incoming.user_id
            ):
                return self._receipt(
                    operation_id=command_operation_id,
                    command_id=command_id,
                    request_fingerprint=request_fingerprint,
                    mutation=mutation,
                    outcome="outcome_unknown",
                    code="canary_operation_identity_mismatch",
                )

            if pre_membership_failure_confirmed(operation):
                finalized = await self._companion.finalize(operation_id)
                if not finalized.released:
                    return self._receipt(
                        operation_id=command_operation_id,
                        command_id=command_id,
                        request_fingerprint=request_fingerprint,
                        mutation=mutation,
                        outcome="outcome_unknown",
                        code="canary_finalize_pending",
                    )
                return self._receipt(
                    operation_id=command_operation_id,
                    command_id=command_id,
                    request_fingerprint=request_fingerprint,
                    mutation=mutation,
                    outcome="authoritative_non_effect",
                    code=f"canary_pre_membership_non_effect:{operation.code}",
                    non_effect=True,
                )

            removed_exact = (
                operation.removed_email is not None
                and operation.removed_user_id is not None
                and operation.removed_email.casefold() == outgoing.email.casefold()
                and operation.removed_user_id == outgoing.user_id
            )
            removal_observed = removed_exact and any(
                entry.stage == "verifying_removal"
                and entry.code == "outgoing_workspace_absence_observed"
                and entry.action is None
                and entry.status is None
                for entry in operation.trace
            )
            settlement = operation.invitation_settlement
            invite_observation = None if settlement is None else settlement.invite_response_observation
            unsafe_capture = any(
                observation is not None and observation.capture_state in _UNSAFE_CAPTURE_STATES
                for observation in (operation.remove_response_observation, invite_observation)
            )
            membership_settled = (
                membership_confirmed(operation)
                and settlement is not None
                and settlement.invitation_issued
                and settlement.final_membership_confirmed
            )
            if membership_settled and removal_observed and not unsafe_capture:
                finalized = await self._companion.finalize(operation_id)
                if not finalized.released:
                    return self._receipt(
                        operation_id=command_operation_id,
                        command_id=command_id,
                        request_fingerprint=request_fingerprint,
                        mutation=mutation,
                        outcome="outcome_unknown",
                        code="canary_finalize_pending",
                    )
                return self._receipt(
                    operation_id=command_operation_id,
                    command_id=command_id,
                    request_fingerprint=request_fingerprint,
                    mutation=mutation,
                    outcome="completed",
                    code="canary_switch_completed",
                    confirmed=True,
                )
            if operation.stage in {"failed", "needs_attention"} or unsafe_capture:
                return self._receipt(
                    operation_id=command_operation_id,
                    command_id=command_id,
                    request_fingerprint=request_fingerprint,
                    mutation=mutation,
                    outcome="outcome_unknown",
                    code=f"canary_effect_unresolved:{operation.code}",
                )
            if asyncio.get_running_loop().time() >= deadline:
                return self._receipt(
                    operation_id=command_operation_id,
                    command_id=command_id,
                    request_fingerprint=request_fingerprint,
                    mutation=mutation,
                    outcome="outcome_unknown",
                    code="canary_settlement_timeout",
                )
            await self._sleep(self._poll_interval_seconds)

    def _local_non_effect(self, command: MembershipMutationCommand, code: str) -> MembershipMutationReceipt:
        return self._receipt(
            operation_id=str(command.operation_id),
            command_id=str(command.command_id),
            request_fingerprint=command.fingerprint(),
            mutation=command.mutation,
            outcome="authoritative_non_effect",
            code=code,
            non_effect=True,
        )

    def _unknown(self, command: MembershipMutationCommand, code: str) -> MembershipMutationReceipt:
        return self._receipt(
            operation_id=str(command.operation_id),
            command_id=str(command.command_id),
            request_fingerprint=command.fingerprint(),
            mutation=command.mutation,
            outcome="outcome_unknown",
            code=code,
        )

    def _receipt(
        self,
        *,
        operation_id: str,
        command_id: str,
        request_fingerprint: str,
        mutation: MembershipMutationSpec,
        outcome: MembershipMutationOutcome,
        code: str,
        confirmed: bool = False,
        non_effect: bool = False,
    ) -> MembershipMutationReceipt:
        remove_effect = "not_attempted"
        add_effect = "not_attempted"
        if mutation.action in {"remove", "switch"}:
            remove_effect = "confirmed" if confirmed else "authoritative_non_effect" if non_effect else "unknown"
        if mutation.action in {"add", "switch"}:
            add_effect = "confirmed" if confirmed else "authoritative_non_effect" if non_effect else "unknown"
        return MembershipMutationReceipt(
            operation_id=operation_id,
            command_id=command_id,
            request_fingerprint=request_fingerprint,
            action=mutation.action,
            workspace_id=mutation.workspace_id,
            workspace_account_id=mutation.workspace_account_id,
            outcome=outcome,
            code=code,
            observed_at=self._clock(),
            remove_effect=remove_effect,
            add_effect=add_effect,
            final_membership_confirmed=confirmed,
        )
