from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.member_switch.companion import CompanionClient
from app.modules.member_switch.repository import MemberSwitchControlRepository
from app.modules.workspace_member_controller.binding_repository import (
    FileWorkspaceMemberAccountBindingRepository,
)
from app.modules.workspace_member_controller.legacy_companion_canary_effect import (
    LegacyCompanionCanarySwitchEffect,
)
from app.modules.workspace_member_controller.legacy_mutation_journal import LegacyMembershipMutationJournal
from app.modules.workspace_member_controller.mutation_admission import WorkspaceMembershipMutationAdmission
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationCommand,
    MembershipMutationSpec,
    MembershipSubject,
)
from app.modules.workspace_member_controller.mutation_service import WorkspaceMembershipMutationService
from app.modules.workspace_member_controller.opencodex_adapter import OpenCodexHttpAccountStateAdapter

_ACK = "single-workspace-canary-with-rollback"


@dataclass(frozen=True, slots=True)
class CanaryIdentity:
    preset_id: str
    email: str
    user_id: str

    def subject_hash(self) -> str:
        return hashlib.sha256(f"{self.email.casefold()}|{self.user_id}".encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class CanaryState:
    schema_version: int
    workspace_id: str
    workspace_account_id: str
    original: CanaryIdentity
    target: CanaryIdentity
    original_opencodex_account_id: str
    target_opencodex_account_id: str
    forward_operation_id: str
    forward_completed_at: str
    rollback_operation_id: str | None = None
    restored_at: str | None = None


def _subject(member) -> CanaryIdentity:
    return CanaryIdentity(member.preset_id, member.email, member.user_id)


async def _current_identity(companion: CompanionClient, workspace_id: str):
    catalog = await companion.catalog()
    workspaces = [workspace for workspace in catalog.workspaces if workspace.id == workspace_id]
    if len(workspaces) != 1:
        raise RuntimeError("canary_workspace_identity_mismatch")
    workspace = workspaces[0]
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
        or observed.catalog_fingerprint != catalog.catalog_fingerprint
    ):
        raise RuntimeError(f"canary_membership_not_authoritative:{observed.code}")
    non_owner = [member for member in observed.members if member.classification != "owner"]
    if len(non_owner) != 1:
        raise RuntimeError("canary_requires_exactly_one_non_owner_member")
    current = [
        member
        for member in workspace.members
        if member.email.casefold() == non_owner[0].email.casefold() and member.user_id == non_owner[0].user_id
    ]
    if len(current) != 1:
        raise RuntimeError("canary_current_member_identity_mismatch")
    return catalog, workspace, _subject(current[0])


def _command(*, catalog, workspace, incoming: CanaryIdentity, outgoing: CanaryIdentity) -> MembershipMutationCommand:
    return MembershipMutationCommand(
        operation_id=uuid4(),
        command_id=uuid4(),
        expected_revision=0,
        mutation=MembershipMutationSpec(
            action="switch",
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
            catalog_fingerprint=catalog.catalog_fingerprint,
            incoming=MembershipSubject(
                preset_id=incoming.preset_id,
                email=incoming.email,
                user_id=incoming.user_id,
            ),
            outgoing=MembershipSubject(
                preset_id=outgoing.preset_id,
                email=outgoing.email,
                user_id=outgoing.user_id,
            ),
        ),
    )


async def _require_exact_account(
    *,
    bindings: FileWorkspaceMemberAccountBindingRepository,
    accounts: OpenCodexHttpAccountStateAdapter,
    workspace_id: str,
    workspace_account_id: str,
    identity: CanaryIdentity,
) -> str:
    binding = await bindings.get_exact(
        workspace_id=workspace_id,
        workspace_account_id=workspace_account_id,
        preset_id=identity.preset_id,
        member_user_id=identity.user_id,
        member_email_normalized=identity.email.casefold(),
    )
    if binding is None:
        raise RuntimeError(f"canary_exact_account_binding_missing:{identity.preset_id}")
    state = await accounts.get(binding.opencodex_account_id)
    if state.account_id != binding.opencodex_account_id:
        raise RuntimeError("canary_opencodex_account_identity_mismatch")
    if not state.has_credential or state.needs_reauth:
        raise RuntimeError(f"canary_opencodex_account_not_usable:{identity.preset_id}")
    if not state.paused:
        raise RuntimeError(f"canary_opencodex_account_not_isolated:{identity.preset_id}")
    return binding.opencodex_account_id


async def _preflight(
    *,
    companion: CompanionClient,
    bindings: FileWorkspaceMemberAccountBindingRepository,
    accounts: OpenCodexHttpAccountStateAdapter,
    controls: MemberSwitchControlRepository,
    workspace_id: str,
    target_preset_id: str,
):
    if await controls.active() is not None:
        raise RuntimeError("canary_control_scope_not_idle")
    external = await companion.admission()
    if not external.can_start:
        raise RuntimeError(f"canary_companion_not_idle:{external.code}")
    catalog, workspace, original = await _current_identity(companion, workspace_id)
    targets = [member for member in workspace.members if member.preset_id == target_preset_id]
    if len(targets) != 1:
        raise RuntimeError("canary_target_identity_mismatch")
    target = _subject(targets[0])
    if target.user_id == original.user_id or target.email.casefold() == original.email.casefold():
        raise RuntimeError("canary_target_already_active")
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
    return catalog, workspace, original, target, original_account_id, target_account_id


def _safe_report(identity: CanaryIdentity) -> dict[str, str]:
    return {"presetId": identity.preset_id, "subjectHash": identity.subject_hash()}


def _write_state(path: Path, state: CanaryState) -> None:
    if not path.is_absolute():
        raise RuntimeError("canary_state_path_must_be_absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(asdict(state), sort_keys=True, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, rendered.encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _read_state(path: Path) -> CanaryState:
    if not path.is_absolute():
        raise RuntimeError("canary_state_path_must_be_absolute")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError("canary_state_permissions_too_open")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CanaryState(
        schema_version=int(payload["schema_version"]),
        workspace_id=str(payload["workspace_id"]),
        workspace_account_id=str(payload["workspace_account_id"]),
        original=CanaryIdentity(**payload["original"]),
        target=CanaryIdentity(**payload["target"]),
        original_opencodex_account_id=str(payload["original_opencodex_account_id"]),
        target_opencodex_account_id=str(payload["target_opencodex_account_id"]),
        forward_operation_id=str(payload["forward_operation_id"]),
        forward_completed_at=str(payload["forward_completed_at"]),
        rollback_operation_id=payload.get("rollback_operation_id"),
        restored_at=payload.get("restored_at"),
    )


async def run_phase(
    *,
    phase: str,
    database_url: str,
    companion_url: str,
    bindings_path: Path,
    opencodex_base_url: str,
    opencodex_admin_token: str,
    workspace_id: str,
    target_preset_id: str,
    state_path: Path,
) -> dict[str, object]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    http = httpx.AsyncClient(trust_env=False)
    companion = CompanionClient(companion_url)
    controls = MemberSwitchControlRepository(sessions)
    bindings = FileWorkspaceMemberAccountBindingRepository(bindings_path)
    accounts = OpenCodexHttpAccountStateAdapter(
        base_url=opencodex_base_url,
        admin_token=opencodex_admin_token,
        client=http,
    )
    journal = LegacyMembershipMutationJournal(controls)
    admission = WorkspaceMembershipMutationAdmission(companion)
    effects = LegacyCompanionCanarySwitchEffect(companion)
    service = WorkspaceMembershipMutationService(journal, admission, effects)
    try:
        if phase in {"preflight", "forward"}:
            catalog, workspace, original, target, original_account_id, target_account_id = await _preflight(
                companion=companion,
                bindings=bindings,
                accounts=accounts,
                controls=controls,
                workspace_id=workspace_id,
                target_preset_id=target_preset_id,
            )
            if phase == "preflight":
                return {
                    "schemaVersion": 1,
                    "phase": "preflight",
                    "ready": True,
                    "workspaceId": workspace_id,
                    "current": _safe_report(original),
                    "target": _safe_report(target),
                    "exactAccountBindings": 2,
                }
            if state_path.exists():
                raise RuntimeError("canary_state_already_exists")
            command = _command(catalog=catalog, workspace=workspace, incoming=target, outgoing=original)
            result = await service.submit(command)
            if result.phase != "completed":
                raise RuntimeError(f"canary_forward_not_completed:{result.phase}:{result.last_code}")
            _after_catalog, _after_workspace, current = await _current_identity(companion, workspace_id)
            if current.user_id != target.user_id or current.email.casefold() != target.email.casefold():
                raise RuntimeError("canary_forward_membership_not_confirmed")
            if await controls.active() is not None:
                raise RuntimeError("canary_scope_not_released_after_forward")
            external = await companion.admission()
            if not external.can_start:
                raise RuntimeError(f"canary_companion_not_idle_after_forward:{external.code}")
            state = CanaryState(
                schema_version=1,
                workspace_id=workspace.id,
                workspace_account_id=workspace.workspace_account_id,
                original=original,
                target=target,
                original_opencodex_account_id=original_account_id,
                target_opencodex_account_id=target_account_id,
                forward_operation_id=str(command.operation_id),
                forward_completed_at=datetime.now(timezone.utc).isoformat(),
            )
            _write_state(state_path, state)
            return {
                "schemaVersion": 1,
                "phase": "forward",
                "completed": True,
                "workspaceId": workspace_id,
                "operationId": str(command.operation_id),
                "from": _safe_report(original),
                "to": _safe_report(target),
                "rollbackRequired": True,
            }

        if phase != "rollback":
            raise RuntimeError("canary_phase_invalid")
        state = _read_state(state_path)
        if (
            state.schema_version != 1
            or state.workspace_id != workspace_id
            or state.target.preset_id != target_preset_id
        ):
            raise RuntimeError("canary_state_identity_mismatch")
        if state.restored_at is not None:
            raise RuntimeError("canary_already_restored")
        if await controls.active() is not None:
            raise RuntimeError("canary_control_scope_not_idle")
        external = await companion.admission()
        if not external.can_start:
            raise RuntimeError(f"canary_companion_not_idle:{external.code}")
        catalog, workspace, current = await _current_identity(companion, workspace_id)
        if current.user_id != state.target.user_id or current.email.casefold() != state.target.email.casefold():
            raise RuntimeError("canary_rollback_current_identity_mismatch")
        original_account_id = await _require_exact_account(
            bindings=bindings,
            accounts=accounts,
            workspace_id=state.workspace_id,
            workspace_account_id=state.workspace_account_id,
            identity=state.original,
        )
        target_account_id = await _require_exact_account(
            bindings=bindings,
            accounts=accounts,
            workspace_id=state.workspace_id,
            workspace_account_id=state.workspace_account_id,
            identity=state.target,
        )
        if (
            original_account_id != state.original_opencodex_account_id
            or target_account_id != state.target_opencodex_account_id
        ):
            raise RuntimeError("canary_rollback_account_binding_changed")
        command = _command(catalog=catalog, workspace=workspace, incoming=state.original, outgoing=current)
        result = await service.submit(command)
        if result.phase != "completed":
            raise RuntimeError(f"canary_rollback_not_completed:{result.phase}:{result.last_code}")
        _final_catalog, _final_workspace, restored = await _current_identity(companion, workspace_id)
        if restored.user_id != state.original.user_id or restored.email.casefold() != state.original.email.casefold():
            raise RuntimeError("canary_rollback_membership_not_restored")
        if await controls.active() is not None:
            raise RuntimeError("canary_scope_not_released_after_rollback")
        external = await companion.admission()
        if not external.can_start:
            raise RuntimeError(f"canary_companion_not_idle_after_rollback:{external.code}")
        restored_state = replace(
            state,
            rollback_operation_id=str(command.operation_id),
            restored_at=datetime.now(timezone.utc).isoformat(),
        )
        _write_state(state_path, restored_state)
        return {
            "schemaVersion": 1,
            "phase": "rollback",
            "completed": True,
            "workspaceId": workspace_id,
            "operationId": str(command.operation_id),
            "restored": _safe_report(restored),
        }
    finally:
        await http.aclose()
        await engine.dispose()


def _read_admin_token(path: Path) -> str:
    if not path.is_absolute():
        raise SystemExit("WMC_CANARY_OPENCODEX_ADMIN_TOKEN_FILE must be absolute")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SystemExit("OpenCodex admin token file permissions are too open")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("OpenCodex admin token is invalid")
    return token


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight or run one forward/rollback membership canary phase.")
    parser.add_argument("--phase", choices=("preflight", "forward", "rollback"), default="preflight")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--target-preset-id", required=True)
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--report-path", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.phase != "preflight" and (
        not args.execute or os.environ.get("WMC_CANARY_MUTATION_ACK") != _ACK
    ):
        raise SystemExit("canary mutation requires --execute and exact WMC_CANARY_MUTATION_ACK")
    required = {
        "WMC_CANARY_DATABASE_URL": os.environ.get("WMC_CANARY_DATABASE_URL", "").strip(),
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
        raise SystemExit("missing canary settings: " + ",".join(missing))
    token = _read_admin_token(Path(required["WMC_CANARY_OPENCODEX_ADMIN_TOKEN_FILE"]))
    report = asyncio.run(
        run_phase(
            phase=args.phase,
            database_url=required["WMC_CANARY_DATABASE_URL"],
            companion_url=required["WMC_CANARY_COMPANION_URL"],
            bindings_path=Path(required["WMC_CANARY_BINDINGS_PATH"]),
            opencodex_base_url=required["WMC_CANARY_OPENCODEX_MANAGEMENT_BASE_URL"],
            opencodex_admin_token=token,
            workspace_id=args.workspace_id,
            target_preset_id=args.target_preset_id,
            state_path=args.state_path,
        )
    )
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.report_path is not None:
        args.report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
