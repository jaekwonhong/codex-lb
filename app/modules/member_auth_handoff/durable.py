from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.member_auth_handoff.catalog import MemberAuthHandoffCatalog, MemberAuthHandoffCatalogEntry
from app.modules.member_auth_handoff.schemas import (
    MemberAuthHandoffPrepareRequest,
    MemberAuthHandoffResponse,
    MemberAuthReconciliationRequest,
    MemberAuthReconciliationResponse,
)
from app.modules.member_auth_handoff.service import (
    MemberAuthHandoffService,
    MemberAuthHandoffStore,
    _Handoff,
)
from app.modules.member_switch.repository import (
    ControlConflict,
    ControlRecord,
    MemberSwitchControlRepository,
    command_fingerprint,
)
from app.modules.member_switch.schemas import Catalog, Identity


class HandoffEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handoff: _Handoff
    managed_run_id: str
    result_ready: bool = False
    result_command_id: str | None = None


def handoff_id_for_operation(operation_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, "codex-lb/handoff/" + operation_id))


class StoredHandoffReader:
    def __init__(self, controls: MemberSwitchControlRepository) -> None:
        self._controls = controls

    async def get_status(self, handoff_id: str) -> MemberAuthHandoffResponse | None:
        record = await self._controls.get("handoff:" + handoff_id)
        return None if record is None else DurableMemberAuthHandoffService._view(record)


class DurableMemberAuthHandoffService(MemberAuthHandoffService):
    """Persisted child state; the parent run owns every mutation admission.

    The delegate owns auth rules. This adapter owns storage and replay boundaries,
    not another orchestration state machine. A crash leaves an explicit pending
    receipt and never starts a second OAuth flow on reconstruction.
    """

    def __init__(self, *args, controls: MemberSwitchControlRepository, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._controls = controls

    def bind_catalog(self, catalog: Catalog) -> None:
        """Use the trusted run catalog for this request, not the legacy overlay.

        This only binds an in-memory snapshot on the request-scoped service. No
        candidate registration, catalog file write or operation adoption occurs.
        """
        snapshot = MemberAuthHandoffCatalog(
            entries=tuple(
                MemberAuthHandoffCatalogEntry(
                    preset_id=member.preset_id,
                    workspace_id=workspace.id,
                    owner_email=workspace.owner_email,
                    workspace_account_id=workspace.workspace_account_id,
                    email=member.email,
                    user_id=member.user_id,
                )
                for workspace in catalog.workspaces
                for member in workspace.members
            ),
            owner_entries=tuple(
                MemberAuthHandoffCatalogEntry(
                    preset_id=workspace.owner_auth.preset_id,
                    workspace_id=workspace.id,
                    owner_email=workspace.owner_email,
                    workspace_account_id=workspace.workspace_account_id,
                    email=workspace.owner_auth.email,
                    user_id=workspace.owner_auth.user_id,
                )
                for workspace in catalog.workspaces
                if workspace.owner_auth is not None
            ),
        )
        if not catalog.enabled:
            raise ControlConflict("auth_catalog_unavailable")
        if snapshot.fingerprint() != catalog.catalog_fingerprint:
            raise ControlConflict("auth_catalog_fingerprint_mismatch")
        self._catalog = snapshot
        self._catalog_registry = None

    @staticmethod
    def _decode(record: ControlRecord) -> HandoffEnvelope:
        if record.kind != "handoff":
            raise ControlConflict("handoff_identity_mismatch")
        try:
            return HandoffEnvelope.model_validate_json(record.payload)
        except ValidationError as exc:
            raise ControlConflict("stored_handoff_invalid") from exc

    @classmethod
    def _view(cls, record: ControlRecord) -> MemberAuthHandoffResponse:
        envelope = cls._decode(record)
        return cls._response(envelope.handoff).model_copy(
            update={
                "revision": record.revision,
                "pending_action": record.pending_action,
                "last_command_id": record.command_id,
            }
        )

    async def _parent(self, run_id: str | None, action: str) -> ControlRecord:
        parent = await self._controls.active()
        if (
            not run_id
            or parent is None
            or parent.id != run_id
            or parent.kind not in {"run", "auth_enrollment"}
            or parent.pending_action != action
        ):
            raise ControlConflict("managed_run_command_required")
        return parent

    def validate_identity(self, identity: Identity, removed_email: str | None = None) -> None:
        catalog = self._catalog_snapshot()
        target = catalog.find_auth_target(
            preset_id=identity.preset_id, email=identity.target_email, user_id=identity.target_user_id
        )
        if (
            catalog.fingerprint() != identity.catalog_fingerprint
            or target is None
            or target.workspace_id != identity.workspace_id
            or target.workspace_account_id != identity.workspace_account_id
        ):
            raise ControlConflict("auth_catalog_identity_mismatch")
        if (
            removed_email
            and len(
                [
                    entry
                    for entry in catalog.entries
                    if entry.workspace_id == identity.workspace_id
                    and entry.email.casefold() == removed_email.casefold()
                ]
            )
            != 1
        ):
            raise ControlConflict("removed_auth_identity_mismatch")

    async def get_status(self, handoff_id: str) -> MemberAuthHandoffResponse | None:
        record = await self._controls.get("handoff:" + handoff_id)
        return None if record is None else self._view(record)

    async def get_for_operation(self, operation_id: str) -> MemberAuthHandoffResponse | None:
        return await self.get_status(handoff_id_for_operation(operation_id))

    async def ensure_device_oauth_available(self, expected_flow_id: str | None = None) -> None:
        current = await self._oauth.current_device_flow_id()
        if current is not None and current != expected_flow_id:
            raise ControlConflict("device_oauth_busy")

    async def reconcile_for_operation(
        self,
        operation_id: str,
        *,
        managed_run_id: str | None = None,
    ) -> MemberAuthHandoffResponse | None:
        """Publish a stored child result without replaying OAuth.

        The delegate result is written once while the child command remains
        pending, then the pending marker is cleared in a second commit. If only
        the second commit was lost, an explicit parent ``reconcile`` may clear
        the child marker after verifying the exact parent/command identity.
        Earlier checkpoints never set ``result_ready`` and therefore remain
        outcome-unknown after a crash.
        """

        parent = await self._controls.active()
        if (
            not managed_run_id
            or parent is None
            or parent.id != managed_run_id
            or parent.kind not in {"run", "auth_enrollment"}
            or parent.pending_action not in {"prepare_auth", "advance_auth"}
        ):
            raise ControlConflict("managed_run_command_required")
        record = await self._controls.get("handoff:" + handoff_id_for_operation(operation_id))
        if record is None:
            return None
        envelope = self._decode(record)
        if envelope.managed_run_id != parent.id:
            raise ControlConflict("handoff_identity_mismatch")
        if record.pending_action is None:
            return self._view(record)
        if (
            record.pending_action != parent.pending_action
            or record.command_id is None
            or record.command_id != parent.command_id
            or not envelope.result_ready
            or envelope.result_command_id != record.command_id
        ):
            return self._view(record)
        saved = await self._controls.save(record, envelope.model_dump_json(), complete=True)
        return self._view(saved)

    async def prepare(
        self,
        request: MemberAuthHandoffPrepareRequest,
        *,
        managed_run_id: str | None = None,
    ) -> MemberAuthHandoffResponse:
        parent = await self._parent(managed_run_id, "prepare_auth")
        handoff_id = handoff_id_for_operation(request.member_switch_operation_id)
        record_id = "handoff:" + handoff_id
        existing = await self._controls.get(record_id)
        if existing is not None:
            envelope = self._decode(existing)
            if envelope.handoff.request != request or envelope.managed_run_id != parent.id:
                raise ControlConflict("handoff_identity_mismatch")
            return self._view(existing)
        envelope = HandoffEnvelope(
            handoff=_Handoff(handoff_id=handoff_id, request=request, state="prepared"),
            managed_run_id=parent.id,
        )
        record = await self._controls.create(record_id, "handoff", envelope.model_dump_json(), own_scope=False)
        record, execute = await self._controls.claim(
            record,
            parent.command_id or "",
            "prepare_auth",
            command_fingerprint("prepare_auth", request.model_dump_json()),
            expected_revision=record.revision,
        )
        if not execute:
            return self._view(record)
        return await self._execute(record, envelope, prepare=True)

    async def advance(
        self,
        handoff_id: str,
        *,
        managed_run_id: str | None = None,
    ) -> MemberAuthHandoffResponse | None:
        parent = await self._parent(managed_run_id, "advance_auth")
        record = await self._controls.get("handoff:" + handoff_id)
        if record is None:
            return None
        envelope = self._decode(record)
        if envelope.managed_run_id != parent.id:
            raise ControlConflict("handoff_identity_mismatch")
        record, execute = await self._controls.claim(
            record,
            parent.command_id or "",
            "advance_auth",
            command_fingerprint("advance_auth", handoff_id),
            expected_revision=record.revision,
        )
        if not execute:
            return self._view(record)
        return await self._execute(record, envelope, prepare=False)

    async def _execute(
        self,
        record: ControlRecord,
        envelope: HandoffEnvelope,
        *,
        prepare: bool,
    ) -> MemberAuthHandoffResponse:
        memory = MemberAuthHandoffStore()
        if not prepare:
            memory.operations[envelope.handoff.handoff_id] = envelope.handoff

        async def checkpoint(handoff: _Handoff) -> None:
            nonlocal record, envelope
            if handoff.handoff_id != envelope.handoff.handoff_id:
                raise ControlConflict("handoff_identity_mismatch")
            envelope = envelope.model_copy(update={"handoff": handoff})
            record = await self._controls.save(record, envelope.model_dump_json())

        delegate = MemberAuthHandoffService(
            self._repository,
            self._oauth,
            store=memory,
            catalog=self._catalog,
            usage_repository=self._usage,
            catalog_registry=self._catalog_registry,
            checkpoint=checkpoint,
        )
        result = (
            await delegate.prepare(envelope.handoff.request)
            if prepare
            else await delegate.advance(envelope.handoff.handoff_id)
        )
        if result is None or result.handoff_id != envelope.handoff.handoff_id:
            raise ControlConflict("handoff_identity_mismatch")
        stored = memory.operations.get(result.handoff_id)
        if stored is None:
            raise ControlConflict("handoff_snapshot_missing")
        envelope = envelope.model_copy(
            update={
                "handoff": stored,
                "result_ready": True,
                "result_command_id": record.command_id,
            }
        )
        # Publish the exact child result before clearing the pending marker.
        # This gives explicit parent reconciliation durable evidence after a
        # crash between the two commits without repeating OAuth or token writes.
        record = await self._controls.save(record, envelope.model_dump_json())
        record = await self._controls.save(record, envelope.model_dump_json(), complete=True)
        return self._view(record)

    async def reconcile_auth(
        self,
        request: MemberAuthReconciliationRequest,
    ) -> MemberAuthReconciliationResponse:
        # Legacy automatic repair must not bypass the run's durable admission.
        raise ControlConflict("managed_run_command_required")
