from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import monotonic
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.member_switch.companion import CompanionClient, CompanionPort
from app.modules.member_switch.repository import ControlConflict, MemberSwitchControlRepository
from app.modules.member_switch.schemas import (
    CANARY_PARTIAL_RECOVERY_CAPABILITY,
    CanaryRecoveryRequest,
    Operation,
)
from app.modules.workspace_member_controller.binding_repository import (
    FileWorkspaceMemberAccountBindingRepository,
)
from app.modules.workspace_member_controller.legacy_canary_runner import (
    CanaryIdentity,
    _database_url_from_environment,
    _read_admin_token,
    _require_exact_account,
    _safe_report,
    _subject,
)
from app.modules.workspace_member_controller.legacy_companion_canary_effect import (
    LegacyCompanionCanarySwitchEffect,
)
from app.modules.workspace_member_controller.legacy_mutation_journal import LegacyMembershipMutationJournal
from app.modules.workspace_member_controller.mutation_admission import WorkspaceMembershipMutationAdmission
from app.modules.workspace_member_controller.mutation_models import MembershipMutationState
from app.modules.workspace_member_controller.mutation_service import WorkspaceMembershipMutationService
from app.modules.workspace_member_controller.opencodex_adapter import OpenCodexHttpAccountStateAdapter

_ACK = "exact-partial-effect-recovery"
_SETTLE_TIMEOUT_SECONDS = 190.0


def _exact_partial_parent(operation: Operation, state: MembershipMutationState) -> bool:
    incoming = state.mutation.incoming
    outgoing = state.mutation.outgoing
    settlement = operation.invitation_settlement
    return bool(
        state.phase == "outcome_unknown"
        and state.receipt is not None
        and state.receipt.outcome == "outcome_unknown"
        and state.mutation.action == "switch"
        and incoming is not None
        and outgoing is not None
        and operation.workspace_id == state.mutation.workspace_id
        and operation.workspace_account_id == state.mutation.workspace_account_id
        and operation.target_email.casefold() == incoming.email.casefold()
        and operation.target_user_id == incoming.user_id
        and operation.removed_email is not None
        and operation.removed_email.casefold() == outgoing.email.casefold()
        and operation.removed_user_id == outgoing.user_id
        and operation.stage == "failed"
        and operation.code == "acceptance_settlement_not_observed"
        and any(
            entry.stage == "verifying_removal"
            and entry.code == "outgoing_workspace_absence_observed"
            and entry.action is None
            and entry.status is None
            for entry in operation.trace
        )
        and settlement is not None
        and settlement.invitation_attempted
        and settlement.invitation_issued
        and not settlement.final_membership_confirmed
        and not settlement.invitation_non_effect_confirmed
        and bool(settlement.pending_invitation_id)
    )


def _exact_completed_recovery(operation: Operation, state: MembershipMutationState) -> bool:
    incoming = state.mutation.incoming
    outgoing = state.mutation.outgoing
    settlement = operation.invitation_settlement
    return bool(
        incoming is not None
        and outgoing is not None
        and operation.workspace_id == state.mutation.workspace_id
        and operation.workspace_account_id == state.mutation.workspace_account_id
        and operation.target_email.casefold() == outgoing.email.casefold()
        and operation.target_user_id == outgoing.user_id
        and operation.removed_email is not None
        and operation.removed_email.casefold() == incoming.email.casefold()
        and operation.removed_user_id == incoming.user_id
        and operation.stage == "completed"
        and operation.code == "member_added"
        and operation.membership_state == "active"
        and any(
            entry.stage == "recovering"
            and entry.code == "recovery_target_invite_absence_observed"
            and entry.action is None
            and entry.status is None
            for entry in operation.trace
        )
        and settlement is not None
        and settlement.invitation_attempted
        and settlement.invitation_issued
        and settlement.final_membership_confirmed
    )


async def _settle_operation(
    companion: CompanionPort,
    operation_id: str,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    timeout_seconds: float = _SETTLE_TIMEOUT_SECONDS,
) -> Operation:
    deadline = monotonic() + timeout_seconds
    while True:
        operation = await companion.operation(operation_id)
        if operation.stage in {"completed", "failed", "needs_attention"}:
            return operation
        if monotonic() >= deadline:
            raise RuntimeError("partial_recovery_settlement_timeout")
        await sleep(1.0)


async def _context(
    *,
    companion: CompanionPort,
    controls: MemberSwitchControlRepository,
    journal: LegacyMembershipMutationJournal,
    bindings: FileWorkspaceMemberAccountBindingRepository,
    accounts: OpenCodexHttpAccountStateAdapter,
    workspace_id: str,
    restore_preset_id: str,
    failed_target_preset_id: str,
):
    active = await controls.active()
    if active is None or active.kind != "controller_membership_mutation" or active.pending_action != "switch":
        raise RuntimeError("partial_recovery_controller_parent_not_retained")
    entry = await journal.get_mutation(active.id)
    if entry is None or entry.operation_id != active.id:
        raise RuntimeError("partial_recovery_controller_parent_missing")
    state = entry.state
    if (
        state.phase != "outcome_unknown"
        or state.receipt is None
        or state.receipt.outcome != "outcome_unknown"
        or state.mutation.action != "switch"
        or state.mutation.incoming is None
        or state.mutation.outgoing is None
    ):
        raise RuntimeError("partial_recovery_controller_parent_not_eligible")
    original = CanaryIdentity(
        state.mutation.outgoing.preset_id or "",
        state.mutation.outgoing.email,
        state.mutation.outgoing.user_id,
    )
    target = CanaryIdentity(
        state.mutation.incoming.preset_id or "",
        state.mutation.incoming.email,
        state.mutation.incoming.user_id,
    )
    if (
        state.mutation.workspace_id != workspace_id
        or original.preset_id != restore_preset_id
        or target.preset_id != failed_target_preset_id
        or not original.preset_id
        or not target.preset_id
    ):
        raise RuntimeError("partial_recovery_requested_identity_mismatch")

    parent_start = await companion.lookup(entry.operation_id)
    if parent_start is None or not parent_start.accepted or not parent_start.operation_id:
        raise RuntimeError("partial_recovery_companion_parent_missing")
    parent_operation = await companion.operation(parent_start.operation_id)
    if not _exact_partial_parent(parent_operation, state):
        raise RuntimeError("partial_recovery_companion_parent_not_eligible")
    prepared_child = None
    if state.recovery is not None:
        prepared_child = await companion.lookup(str(state.recovery.client_flow_id))
    admission = await companion.admission()
    if state.recovery is None or prepared_child is None:
        if (
            admission.can_start
            or admission.code != "managed_flow_retained"
            or admission.operation_id != parent_start.operation_id
            or admission.client_flow_id != entry.operation_id
        ):
            raise RuntimeError("partial_recovery_companion_parent_not_retained")
    elif not admission.can_start:
        retained_pairs = {
            (entry.operation_id, parent_start.operation_id),
            (str(state.recovery.client_flow_id), prepared_child.operation_id),
        }
        if (admission.client_flow_id, admission.operation_id) not in retained_pairs:
            raise RuntimeError("partial_recovery_companion_recovery_not_retained")

    catalog = await companion.catalog()
    if not catalog.enabled or CANARY_PARTIAL_RECOVERY_CAPABILITY not in catalog.capabilities:
        raise RuntimeError("partial_recovery_catalog_not_qualified")
    workspaces = [workspace for workspace in catalog.workspaces if workspace.id == workspace_id]
    if len(workspaces) != 1:
        raise RuntimeError("partial_recovery_workspace_identity_mismatch")
    workspace = workspaces[0]
    if (
        workspace.workspace_account_id != state.mutation.workspace_account_id
        or catalog.catalog_fingerprint != state.mutation.catalog_fingerprint
    ):
        raise RuntimeError("partial_recovery_catalog_identity_changed")
    restore_members = [member for member in workspace.members if member.preset_id == restore_preset_id]
    target_members = [member for member in workspace.members if member.preset_id == failed_target_preset_id]
    if len(restore_members) != 1 or _subject(restore_members[0]) != original:
        raise RuntimeError("partial_recovery_restore_identity_mismatch")
    if len(target_members) != 1 or _subject(target_members[0]) != target:
        raise RuntimeError("partial_recovery_failed_target_identity_mismatch")
    original_account_id = await _require_exact_account(
        bindings=bindings,
        accounts=accounts,
        workspace_id=workspace.id,
        workspace_account_id=workspace.workspace_account_id,
        identity=original,
    )
    target_account_id = await _require_exact_account(
        bindings=bindings,
        accounts=accounts,
        workspace_id=workspace.id,
        workspace_account_id=workspace.workspace_account_id,
        identity=target,
    )
    return (
        entry,
        state,
        catalog,
        workspace,
        original,
        target,
        original_account_id,
        target_account_id,
        parent_start.operation_id,
        prepared_child,
    )


async def run_recovery(
    *,
    execute: bool,
    companion: CompanionPort,
    controls: MemberSwitchControlRepository,
    journal: LegacyMembershipMutationJournal,
    service: WorkspaceMembershipMutationService,
    bindings: FileWorkspaceMemberAccountBindingRepository,
    accounts: OpenCodexHttpAccountStateAdapter,
    workspace_id: str,
    restore_preset_id: str,
    failed_target_preset_id: str,
) -> dict[str, object]:
    (
        entry,
        state,
        catalog,
        workspace,
        original,
        target,
        _original_account_id,
        _target_account_id,
        parent_operation_id,
        prepared_child,
    ) = await _context(
        companion=companion,
        controls=controls,
        journal=journal,
        bindings=bindings,
        accounts=accounts,
        workspace_id=workspace_id,
        restore_preset_id=restore_preset_id,
        failed_target_preset_id=failed_target_preset_id,
    )
    if not execute:
        return {
            "schemaVersion": 1,
            "phase": "partial-recovery-preflight",
            "ready": True,
            "workspaceId": workspace.id,
            "original": _safe_report(original),
            "failedTarget": _safe_report(target),
            "parentRetained": True,
            "recoveryPrepared": state.recovery is not None,
        }

    if state.recovery is None:
        child_flow_id = str(uuid4())
        prepared = await service.prepare_partial_recovery(entry.operation_id, recovery_client_flow_id=child_flow_id)
        if prepared.recovery is None:
            raise RuntimeError("partial_recovery_prepare_failed")
    else:
        child_flow_id = str(state.recovery.client_flow_id)

    child_start = prepared_child or await companion.lookup(child_flow_id)
    if child_start is None:
        if state.recovery is not None:
            raise RuntimeError("partial_recovery_prepared_start_not_observed")
        request = CanaryRecoveryRequest(
            client_flow_id=child_flow_id,
            parent_client_flow_id=entry.operation_id,
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
            restore_preset_id=original.preset_id,
            failed_target_preset_id=target.preset_id,
            catalog_fingerprint=catalog.catalog_fingerprint,
        )
        try:
            child_start = await companion.start_canary_recovery(request)
        except ControlConflict as exc:
            if exc.code != "companion_outcome_unknown":
                raise
            child_start = await companion.lookup(child_flow_id)
            if child_start is None:
                raise RuntimeError("partial_recovery_start_outcome_unknown") from exc
    if not child_start.accepted or not child_start.operation_id:
        raise RuntimeError(f"partial_recovery_start_rejected:{child_start.code}")

    child_operation = await _settle_operation(companion, child_start.operation_id)
    if not _exact_completed_recovery(child_operation, state):
        raise RuntimeError(f"partial_recovery_not_completed:{child_operation.stage}:{child_operation.code}")

    child_lookup = await companion.lookup(child_flow_id)
    child_already_finalized = child_lookup is not None and child_lookup.code == "operation_finalized"
    if not child_already_finalized:
        try:
            finalized = await companion.finalize(child_start.operation_id)
        except ControlConflict as exc:
            if exc.code != "companion_outcome_unknown":
                raise
            child_lookup = await companion.lookup(child_flow_id)
            external = await companion.admission()
            if child_lookup is None or child_lookup.code != "operation_finalized" or not external.can_start:
                raise RuntimeError("partial_recovery_finalize_outcome_unknown") from exc
        else:
            if not finalized.released:
                raise RuntimeError(f"partial_recovery_finalize_pending:{finalized.code}")
    after_catalog = await companion.catalog()
    observed = await companion.observe_membership(workspace.id)
    if (
        not observed.available
        or not observed.complete
        or not observed.owner_verified
        or observed.identity_ambiguous
        or observed.partial_identity
        or observed.duplicate_identity
        or observed.unknown_member
        or observed.workspace_account_id != workspace.workspace_account_id
        or observed.catalog_fingerprint != after_catalog.catalog_fingerprint
    ):
        raise RuntimeError(f"partial_recovery_restoration_not_authoritative:{observed.code}")
    non_owner = [member for member in observed.members if member.classification != "owner"]
    if len(non_owner) != 1 or (
        non_owner[0].email.casefold() != original.email.casefold()
        or non_owner[0].user_id != original.user_id
    ):
        raise RuntimeError("partial_recovery_original_membership_not_restored")

    completed = await service.complete_partial_recovery(
        entry.operation_id,
        recovery_client_flow_id=child_flow_id,
        companion_operation_id=child_start.operation_id,
        cleanup_confirmed=True,
        restoration_confirmed=True,
    )
    if completed.phase != "recovered" or await controls.active() is not None:
        raise RuntimeError("partial_recovery_controller_scope_not_released")
    external = await companion.admission()
    if not external.can_start:
        raise RuntimeError(f"partial_recovery_companion_not_idle:{external.code}")
    return {
        "schemaVersion": 1,
        "phase": "partial-recovery",
        "completed": True,
        "workspaceId": workspace.id,
        "restored": _safe_report(original),
        "cleanupConfirmed": True,
        "restorationConfirmed": True,
    }


async def run_with_environment(
    *,
    execute: bool,
    database_url: str,
    companion_url: str,
    bindings_path: Path,
    opencodex_base_url: str,
    opencodex_admin_token: str,
    workspace_id: str,
    restore_preset_id: str,
    failed_target_preset_id: str,
) -> dict[str, object]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    http = httpx.AsyncClient(trust_env=False)
    companion = CompanionClient(companion_url)
    controls = MemberSwitchControlRepository(sessions)
    journal = LegacyMembershipMutationJournal(controls)
    bindings = FileWorkspaceMemberAccountBindingRepository(bindings_path)
    accounts = OpenCodexHttpAccountStateAdapter(
        base_url=opencodex_base_url,
        admin_token=opencodex_admin_token,
        client=http,
    )
    service = WorkspaceMembershipMutationService(
        journal,
        WorkspaceMembershipMutationAdmission(companion),
        LegacyCompanionCanarySwitchEffect(companion),
    )
    try:
        return await run_recovery(
            execute=execute,
            companion=companion,
            controls=controls,
            journal=journal,
            service=service,
            bindings=bindings,
            accounts=accounts,
            workspace_id=workspace_id,
            restore_preset_id=restore_preset_id,
            failed_target_preset_id=failed_target_preset_id,
        )
    finally:
        await http.aclose()
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight or run one exact partial-effect canary recovery.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--restore-preset-id", required=True)
    parser.add_argument("--failed-target-preset-id", required=True)
    parser.add_argument("--report-path", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.execute and os.environ.get("WMC_CANARY_RECOVERY_ACK") != _ACK:
        raise SystemExit("partial recovery requires exact WMC_CANARY_RECOVERY_ACK")
    database_url = _database_url_from_environment()
    required = {
        "WMC_CANARY_COMPANION_URL": os.environ.get("WMC_CANARY_COMPANION_URL", "").strip(),
        "WMC_CANARY_BINDINGS_PATH": os.environ.get("WMC_CANARY_BINDINGS_PATH", "").strip(),
        "WMC_CANARY_OPENCODEX_MANAGEMENT_BASE_URL": os.environ.get(
            "WMC_CANARY_OPENCODEX_MANAGEMENT_BASE_URL", ""
        ).strip(),
        "WMC_CANARY_OPENCODEX_ADMIN_TOKEN_FILE": os.environ.get(
            "WMC_CANARY_OPENCODEX_ADMIN_TOKEN_FILE", ""
        ).strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise SystemExit("missing recovery settings: " + ",".join(missing))
    token = _read_admin_token(Path(required["WMC_CANARY_OPENCODEX_ADMIN_TOKEN_FILE"]))
    report = asyncio.run(
        run_with_environment(
            execute=args.execute,
            database_url=database_url,
            companion_url=required["WMC_CANARY_COMPANION_URL"],
            bindings_path=Path(required["WMC_CANARY_BINDINGS_PATH"]),
            opencodex_base_url=required["WMC_CANARY_OPENCODEX_MANAGEMENT_BASE_URL"],
            opencodex_admin_token=token,
            workspace_id=args.workspace_id,
            restore_preset_id=args.restore_preset_id,
            failed_target_preset_id=args.failed_target_preset_id,
        )
    )
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.report_path is not None:
        args.report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
