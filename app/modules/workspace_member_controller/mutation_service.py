from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationCommand,
    MembershipMutationReceipt,
    MembershipMutationState,
    MembershipMutationView,
)
from app.modules.workspace_member_controller.mutation_ports import (
    MembershipMutationAdmissionPort,
    MembershipMutationEffectPort,
)
from app.modules.workspace_member_controller.persistence import (
    MembershipMutationJournal,
    MembershipMutationJournalEntry,
)


class MembershipMutationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkspaceMembershipMutationService:
    def __init__(
        self,
        journal: MembershipMutationJournal,
        admission: MembershipMutationAdmissionPort,
        effects: MembershipMutationEffectPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._journal = journal
        self._admission = admission
        self._effects = effects
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def get(self, operation_id: str) -> MembershipMutationView | None:
        entry = await self._journal.get_mutation(operation_id)
        return None if entry is None else self._view(entry)

    async def submit(self, command: MembershipMutationCommand) -> MembershipMutationView:
        operation_id = str(command.operation_id)
        fingerprint = command.fingerprint()
        entry = await self._journal.get_mutation(operation_id)
        fresh_admission = None
        created_now = False
        if entry is None:
            fresh_admission = await self._admission.validate(command)
            now = self._clock()
            state = MembershipMutationState(
                operation_id=operation_id,
                mutation=command.mutation,
                command_fingerprint=fingerprint,
                phase="ready",
                last_code="mutation_ready",
                created_at=now,
                updated_at=now,
                admission=fresh_admission,
            )
            try:
                entry = await self._journal.create_mutation(state)
            except Exception as exc:
                self._raise_journal_error(exc)
            created_now = True
        self._require_same_operation(entry, command, fingerprint)
        if entry.state.phase in {"completed", "failed"} and entry.command_id != str(command.command_id):
            raise MembershipMutationError("mutation_operation_terminal")

        if not created_now and entry.command_id is None and entry.pending_action is None:
            fresh_admission = await self._admission.validate(command)
            if (
                entry.state.admission is None
                or fresh_admission.workspace_id != entry.state.admission.workspace_id
                or fresh_admission.workspace_account_id != entry.state.admission.workspace_account_id
                or fresh_admission.catalog_fingerprint != entry.state.admission.catalog_fingerprint
            ):
                raise MembershipMutationError("mutation_admission_identity_changed")

        try:
            claim = await self._journal.claim_mutation(
                entry,
                command_id=str(command.command_id),
                action=command.mutation.action,
                fingerprint=fingerprint,
                expected_revision=command.expected_revision,
            )
        except Exception as exc:
            self._raise_journal_error(exc)
        entry = claim.entry
        if not claim.execute:
            return self._view(entry)

        pending = entry.state.model_copy(
            update={
                "phase": "effect_pending",
                "last_code": "mutation_effect_pending",
                "updated_at": self._clock(),
                **({"admission": fresh_admission} if fresh_admission is not None else {}),
            }
        )
        try:
            entry = await self._journal.save_mutation(entry, pending, complete=False, release=False)
        except Exception as exc:
            self._raise_journal_error(exc)

        try:
            receipt = await self._effects.execute(command)
        except Exception as exc:
            raise MembershipMutationError("mutation_outcome_unknown") from exc
        return await self._apply_receipt(entry, receipt)

    async def reconcile(self, operation_id: str) -> MembershipMutationView:
        entry = await self._journal.get_mutation(operation_id)
        if entry is None:
            raise MembershipMutationError("mutation_operation_not_found")
        if entry.pending_action is None:
            return self._view(entry)
        if not entry.command_id:
            raise MembershipMutationError("mutation_pending_command_missing")
        try:
            receipt = await self._effects.reconcile(
                operation_id=entry.operation_id,
                command_id=entry.command_id,
                request_fingerprint=entry.state.command_fingerprint,
            )
        except Exception as exc:
            raise MembershipMutationError("mutation_reconciliation_unavailable") from exc
        if receipt is None:
            raise MembershipMutationError("mutation_outcome_still_unknown")
        return await self._apply_receipt(entry, receipt)

    async def _apply_receipt(
        self,
        entry: MembershipMutationJournalEntry,
        receipt: MembershipMutationReceipt,
    ) -> MembershipMutationView:
        self._require_receipt_identity(entry, receipt)
        if receipt.outcome == "outcome_unknown":
            state = entry.state.model_copy(
                update={
                    "phase": "outcome_unknown",
                    "last_code": receipt.code,
                    "updated_at": self._clock(),
                    "receipt": receipt,
                }
            )
            try:
                saved = await self._journal.save_mutation(entry, state, complete=False, release=False)
            except Exception as exc:
                self._raise_journal_error(exc)
            return self._view(saved)

        phase = "completed" if receipt.outcome == "completed" else "failed"
        state = entry.state.model_copy(
            update={
                "phase": phase,
                "last_code": receipt.code,
                "updated_at": self._clock(),
                "receipt": receipt,
            }
        )
        try:
            saved = await self._journal.save_mutation(entry, state, complete=True, release=True)
        except Exception as exc:
            self._raise_journal_error(exc)
        return self._view(saved)

    @staticmethod
    def _require_same_operation(
        entry: MembershipMutationJournalEntry,
        command: MembershipMutationCommand,
        fingerprint: str,
    ) -> None:
        if entry.kind != "controller_membership_mutation":
            raise MembershipMutationError("mutation_record_identity_mismatch")
        if entry.operation_id != str(command.operation_id):
            raise MembershipMutationError("mutation_record_identity_mismatch")
        if entry.state.mutation != command.mutation:
            raise MembershipMutationError("mutation_operation_identity_mismatch")
        if entry.state.command_fingerprint != fingerprint:
            raise MembershipMutationError("mutation_command_identity_mismatch")

    @staticmethod
    def _require_receipt_identity(
        entry: MembershipMutationJournalEntry,
        receipt: MembershipMutationReceipt,
    ) -> None:
        mutation = entry.state.mutation
        if (
            receipt.operation_id != entry.operation_id
            or receipt.command_id != entry.command_id
            or receipt.request_fingerprint != entry.state.command_fingerprint
            or receipt.action != mutation.action
            or receipt.workspace_id != mutation.workspace_id
            or receipt.workspace_account_id != mutation.workspace_account_id
        ):
            raise MembershipMutationError("mutation_receipt_identity_mismatch")

    @staticmethod
    def _view(entry: MembershipMutationJournalEntry) -> MembershipMutationView:
        phase = (
            "outcome_unknown"
            if entry.pending_action and entry.state.phase == "effect_pending"
            else entry.state.phase
        )
        last_code = (
            "mutation_outcome_unknown"
            if phase == "outcome_unknown" and entry.state.phase == "effect_pending"
            else entry.state.last_code
        )
        return MembershipMutationView(
            operation_id=entry.operation_id,
            revision=entry.revision,
            mutation=entry.state.mutation,
            phase=phase,
            last_code=last_code,
            updated_at=entry.state.updated_at,
            pending_action=entry.pending_action,
            command_id=entry.command_id,
            receipt=entry.state.receipt,
        )

    @staticmethod
    def _raise_journal_error(exc: Exception) -> None:
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            raise MembershipMutationError(code) from exc
        raise MembershipMutationError("mutation_journal_error") from exc
