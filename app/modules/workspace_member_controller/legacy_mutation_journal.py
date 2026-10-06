from __future__ import annotations

from app.modules.member_switch.repository import (
    ControlConflict,
    MemberSwitchControlRepository,
)
from app.modules.workspace_member_controller.mutation_models import MembershipMutationState
from app.modules.workspace_member_controller.persistence import (
    MembershipMutationClaim,
    MembershipMutationJournal,
    MembershipMutationJournalEntry,
)


class LegacyMutationJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LegacyMembershipMutationJournal(MembershipMutationJournal):
    """Migration adapter over the existing durable member-switch CAS journal."""

    KIND = "controller_membership_mutation"

    def __init__(self, controls: MemberSwitchControlRepository) -> None:
        self._controls = controls

    @classmethod
    def _convert(cls, record) -> MembershipMutationJournalEntry:
        if record.kind != cls.KIND:
            raise LegacyMutationJournalError("mutation_record_identity_mismatch")
        try:
            state = MembershipMutationState.model_validate_json(record.payload)
        except ValueError as exc:
            raise LegacyMutationJournalError("stored_mutation_invalid") from exc
        if state.operation_id != record.id:
            raise LegacyMutationJournalError("mutation_record_identity_mismatch")
        if state.receipt is not None and state.receipt.command_id != record.command_id:
            raise LegacyMutationJournalError("mutation_receipt_identity_mismatch")
        return MembershipMutationJournalEntry(
            operation_id=record.id,
            kind=record.kind,
            active_scope=record.active_scope,
            revision=record.revision,
            state=state,
            pending_action=record.pending_action,
            command_id=record.command_id,
        )

    async def get_mutation(self, operation_id: str) -> MembershipMutationJournalEntry | None:
        record = await self._controls.get(operation_id)
        return None if record is None else self._convert(record)

    async def create_mutation(self, state: MembershipMutationState) -> MembershipMutationJournalEntry:
        try:
            record = await self._controls.create(
                state.operation_id,
                self.KIND,
                state.model_dump_json(by_alias=True),
                own_scope=True,
            )
        except ControlConflict as exc:
            raise LegacyMutationJournalError(exc.code) from exc
        return self._convert(record)

    async def claim_mutation(
        self,
        current: MembershipMutationJournalEntry,
        *,
        command_id: str,
        action: str,
        fingerprint: str,
        expected_revision: int,
    ) -> MembershipMutationClaim:
        record = await self._controls.get(current.operation_id)
        if record is None:
            raise LegacyMutationJournalError("mutation_operation_not_found")
        if record.revision != current.revision:
            raise LegacyMutationJournalError("revision_conflict")
        try:
            claimed, execute = await self._controls.claim(
                record,
                command_id,
                action,
                fingerprint,
                expected_revision=expected_revision,
            )
        except ControlConflict as exc:
            raise LegacyMutationJournalError(exc.code) from exc
        return MembershipMutationClaim(self._convert(claimed), execute)

    async def save_mutation(
        self,
        current: MembershipMutationJournalEntry,
        state: MembershipMutationState,
        *,
        complete: bool,
        release: bool,
    ) -> MembershipMutationJournalEntry:
        if state.operation_id != current.operation_id:
            raise LegacyMutationJournalError("mutation_record_identity_mismatch")
        record = await self._controls.get(current.operation_id)
        if record is None:
            raise LegacyMutationJournalError("mutation_operation_not_found")
        if record.revision != current.revision or record.command_id != current.command_id:
            raise LegacyMutationJournalError("revision_conflict")
        try:
            saved = await self._controls.save(
                record,
                state.model_dump_json(by_alias=True),
                complete=complete,
                release=release,
            )
        except ControlConflict as exc:
            raise LegacyMutationJournalError(exc.code) from exc
        return self._convert(saved)
