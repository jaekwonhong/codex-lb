from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.workspace_member_controller.account_state import AccountDecisionEvidence
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationAdmissionEvidence,
    MembershipMutationCommand,
    MembershipMutationReceipt,
    MembershipMutationSpec,
    MembershipSubject,
)
from app.modules.workspace_member_controller.mutation_service import (
    MembershipMutationError,
    WorkspaceMembershipMutationService,
)
from app.modules.workspace_member_controller.persistence import (
    MembershipMutationClaim,
    MembershipMutationJournalEntry,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
OPERATION_ID = UUID("11111111-1111-4111-8111-111111111111")
COMMAND_ID = UUID("22222222-2222-4222-8222-222222222222")


def member(name: str) -> MembershipSubject:
    return MembershipSubject(
        preset_id=name,
        email=f"{name}@example.com",
        user_id=f"user-{name.title()}",
    )


def mutation(action: str = "switch") -> MembershipMutationSpec:
    return MembershipMutationSpec(
        action=action,
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        catalog_fingerprint="a" * 64,
        incoming=member("incoming") if action in {"add", "switch"} else None,
        outgoing=member("outgoing") if action in {"remove", "switch"} else None,
    )


def command(action: str = "switch", *, command_id: UUID = COMMAND_ID, expected_revision: int = 0):
    return MembershipMutationCommand(
        operation_id=OPERATION_ID,
        command_id=command_id,
        expected_revision=expected_revision,
        mutation=mutation(action),
    )


def decision_evidence() -> AccountDecisionEvidence:
    return AccountDecisionEvidence(
        account_id="acct-outgoing",
        credential_generation=7,
        state_revision="d" * 64,
        observed_at=1_000_000,
        quota_observed_at=999_000,
        selection_state="excluded",
        quota_state="exhausted",
        needs_reauth=False,
        paused=False,
        reset_credit_available_count=0,
    )


def completed_receipt(cmd: MembershipMutationCommand) -> MembershipMutationReceipt:
    return MembershipMutationReceipt(
        operation_id=str(cmd.operation_id),
        command_id=str(cmd.command_id),
        request_fingerprint=cmd.fingerprint(),
        action=cmd.mutation.action,
        workspace_id=cmd.mutation.workspace_id,
        workspace_account_id=cmd.mutation.workspace_account_id,
        outcome="completed",
        code="membership_mutation_completed",
        observed_at=NOW,
        remove_effect="confirmed" if cmd.mutation.action in {"remove", "switch"} else "not_attempted",
        add_effect="confirmed" if cmd.mutation.action in {"add", "switch"} else "not_attempted",
        final_membership_confirmed=True,
    )


def unknown_receipt(cmd: MembershipMutationCommand) -> MembershipMutationReceipt:
    return MembershipMutationReceipt(
        operation_id=str(cmd.operation_id),
        command_id=str(cmd.command_id),
        request_fingerprint=cmd.fingerprint(),
        action=cmd.mutation.action,
        workspace_id=cmd.mutation.workspace_id,
        workspace_account_id=cmd.mutation.workspace_account_id,
        outcome="outcome_unknown",
        code="canary_effect_unresolved:acceptance_settlement_not_observed",
        observed_at=NOW,
        remove_effect="unknown",
        add_effect="unknown",
        final_membership_confirmed=False,
    )


class MemoryJournal:
    def __init__(self):
        self.entry = None
        self.receipts = {}
        self.events = []

    async def get_mutation(self, operation_id):
        return self.entry if self.entry and self.entry.operation_id == operation_id else None

    async def create_mutation(self, state):
        self.events.append("create")
        if self.entry is not None:
            raise JournalError("flow_busy_or_id_exists")
        self.entry = MembershipMutationJournalEntry(
            operation_id=state.operation_id,
            kind="controller_membership_mutation",
            active_scope="member-switch",
            revision=0,
            state=state,
            pending_action=None,
            command_id=None,
        )
        return self.entry

    async def claim_mutation(self, current, *, command_id, action, fingerprint, expected_revision):
        recorded = self.receipts.get(command_id)
        if recorded is not None:
            if recorded != fingerprint:
                raise JournalError("command_identity_mismatch")
            return MembershipMutationClaim(self.entry, False)
        if current.pending_action:
            raise JournalError("outcome_unknown")
        if current.revision != expected_revision:
            raise JournalError("revision_conflict")
        self.events.append("claim")
        self.receipts[command_id] = fingerprint
        self.entry = replace(
            current,
            revision=current.revision + 1,
            pending_action=action,
            command_id=command_id,
        )
        return MembershipMutationClaim(self.entry, True)

    async def save_mutation(self, current, state, *, complete, release):
        if self.entry.revision != current.revision or self.entry.command_id != current.command_id:
            raise JournalError("revision_conflict")
        self.events.append("settle" if complete else "save_pending")
        self.entry = replace(
            current,
            revision=current.revision + 1,
            state=state,
            active_scope=None if release else current.active_scope,
            pending_action=None if complete else current.pending_action,
        )
        return self.entry


class JournalError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PermitAdmission:
    def __init__(self):
        self.calls = []

    async def validate(self, cmd):
        self.calls.append(cmd)
        return MembershipMutationAdmissionEvidence(
            workspace_id=cmd.mutation.workspace_id,
            workspace_account_id=cmd.mutation.workspace_account_id,
            catalog_fingerprint=cmd.mutation.catalog_fingerprint,
            membership_observed_at=NOW,
        )


class Effects:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.execute_calls = []
        self.reconcile_calls = []
        self.journal = None

    async def execute(self, cmd):
        self.execute_calls.append(cmd)
        assert self.journal.entry.pending_action == cmd.mutation.action
        assert self.journal.entry.command_id == str(cmd.command_id)
        assert self.journal.entry.state.phase == "effect_pending"
        if self.error:
            raise self.error
        return self.response or completed_receipt(cmd)

    async def reconcile(self, *, operation_id, command_id, request_fingerprint, mutation):
        self.reconcile_calls.append((operation_id, command_id, request_fingerprint, mutation))
        return self.response


class EvidenceGuard:
    def __init__(self, journal, *, error=None):
        self.journal = journal
        self.error = error
        self.calls = []

    async def revalidate_account_evidence(self, evidence):
        self.calls.append(evidence)
        assert self.journal.entry.pending_action == "switch"
        assert self.journal.entry.state.phase == "effect_pending"
        assert self.journal.entry.state.account_decision_evidence == evidence
        if self.error:
            raise self.error
        return object()


@pytest.mark.parametrize("action", ["add", "remove", "switch"])
async def test_add_remove_switch_claim_before_effect_and_settle(action):
    journal = MemoryJournal()
    effects = Effects()
    effects.journal = journal
    admission = PermitAdmission()
    service = WorkspaceMembershipMutationService(journal, admission, effects, clock=lambda: NOW)
    cmd = command(action)

    result = await service.submit(cmd)

    assert result.phase == "completed"
    assert result.pending_action is None
    assert result.receipt is not None and result.receipt.outcome == "completed"
    assert journal.events == ["create", "claim", "save_pending", "settle"]
    assert len(effects.execute_calls) == 1
    assert len(admission.calls) == 1
    assert journal.entry.active_scope is None


async def test_lost_effect_reply_stays_pending_and_duplicate_command_does_not_replay():
    journal = MemoryJournal()
    effects = Effects(error=RuntimeError("reply lost"))
    effects.journal = journal
    admission = PermitAdmission()
    service = WorkspaceMembershipMutationService(journal, admission, effects, clock=lambda: NOW)
    cmd = command()

    with pytest.raises(MembershipMutationError, match="mutation_outcome_unknown"):
        await service.submit(cmd)
    assert journal.entry.pending_action == "switch"
    assert journal.entry.state.phase == "effect_pending"
    assert len(effects.execute_calls) == 1

    replay = await service.submit(cmd)
    assert replay.phase == "outcome_unknown"
    assert replay.pending_action == "switch"
    assert len(effects.execute_calls) == 1
    assert len(admission.calls) == 1


async def test_restart_reconciles_same_command_receipt_without_execute_replay():
    journal = MemoryJournal()
    first = Effects(error=RuntimeError("reply lost"))
    first.journal = journal
    cmd = command()
    with pytest.raises(MembershipMutationError, match="mutation_outcome_unknown"):
        await WorkspaceMembershipMutationService(journal, PermitAdmission(), first, clock=lambda: NOW).submit(cmd)

    recovered = Effects(response=completed_receipt(cmd))
    recovered.journal = journal
    service = WorkspaceMembershipMutationService(journal, PermitAdmission(), recovered, clock=lambda: NOW)
    result = await service.reconcile(str(OPERATION_ID))

    assert result.phase == "completed"
    assert recovered.execute_calls == []
    assert recovered.reconcile_calls == [(str(OPERATION_ID), str(COMMAND_ID), cmd.fingerprint(), cmd.mutation)]
    assert journal.entry.active_scope is None


async def test_unknown_reconciliation_never_replays_effect():
    journal = MemoryJournal()
    effects = Effects(error=RuntimeError("reply lost"))
    effects.journal = journal
    cmd = command()
    with pytest.raises(MembershipMutationError):
        await WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW).submit(cmd)

    effects.error = None
    effects.response = None
    with pytest.raises(MembershipMutationError, match="mutation_outcome_still_unknown"):
        await WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW).reconcile(
            str(OPERATION_ID)
        )
    assert len(effects.execute_calls) == 1


async def test_reused_command_id_with_different_identity_fails_closed():
    journal = MemoryJournal()
    effects = Effects(error=RuntimeError("reply lost"))
    effects.journal = journal
    original = command()
    with pytest.raises(MembershipMutationError):
        service = WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW)
        await service.submit(original)

    changed = original.model_copy(
        update={"mutation": original.mutation.model_copy(update={"catalog_fingerprint": "b" * 64})}
    )
    with pytest.raises(
        MembershipMutationError,
        match="mutation_operation_identity_mismatch|mutation_command_identity_mismatch",
    ):
        await WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW).submit(changed)
    assert len(effects.execute_calls) == 1


async def test_receipt_identity_mismatch_stays_pending_for_manual_reconciliation():
    journal = MemoryJournal()
    cmd = command()
    bad = completed_receipt(cmd).model_copy(update={"workspace_account_id": "other-workspace-account"})
    effects = Effects(response=bad)
    effects.journal = journal
    with pytest.raises(MembershipMutationError, match="mutation_receipt_identity_mismatch"):
        await WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW).submit(cmd)
    assert journal.entry.pending_action == "switch"
    assert journal.entry.active_scope == "member-switch"


async def test_authoritative_non_effect_is_terminal_and_releases_scope():
    journal = MemoryJournal()
    cmd = command("remove")
    receipt = MembershipMutationReceipt(
        operation_id=str(cmd.operation_id),
        command_id=str(cmd.command_id),
        request_fingerprint=cmd.fingerprint(),
        action="remove",
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
        outcome="authoritative_non_effect",
        code="remove_not_sent",
        observed_at=NOW,
        remove_effect="authoritative_non_effect",
    )
    effects = Effects(response=receipt)
    effects.journal = journal
    service = WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW)
    result = await service.submit(cmd)
    assert result.phase == "failed"
    assert result.pending_action is None
    assert journal.entry.active_scope is None


async def test_account_decision_evidence_is_persisted_and_revalidated_after_durable_claim():
    journal = MemoryJournal()
    effects = Effects()
    effects.journal = journal
    evidence = decision_evidence()
    cmd = command().model_copy(update={"account_decision_evidence": evidence})
    guard = EvidenceGuard(journal)
    service = WorkspaceMembershipMutationService(
        journal,
        PermitAdmission(),
        effects,
        account_evidence_guard=guard,
        clock=lambda: NOW,
    )

    result = await service.submit(cmd)

    assert result.phase == "completed"
    assert result.account_decision_evidence == evidence
    assert journal.entry.state.account_decision_evidence == evidence
    assert guard.calls == [evidence]
    assert len(effects.execute_calls) == 1


async def test_changed_account_evidence_after_claim_closes_as_authoritative_non_effect_without_execute():
    class Changed(RuntimeError):
        code = "rotation_account_evidence_changed"

    journal = MemoryJournal()
    effects = Effects()
    effects.journal = journal
    evidence = decision_evidence()
    cmd = command().model_copy(update={"account_decision_evidence": evidence})
    guard = EvidenceGuard(journal, error=Changed("changed"))
    service = WorkspaceMembershipMutationService(
        journal,
        PermitAdmission(),
        effects,
        account_evidence_guard=guard,
        clock=lambda: NOW,
    )

    result = await service.submit(cmd)

    assert result.phase == "failed"
    assert result.pending_action is None
    assert result.last_code == "rotation_account_evidence_changed"
    assert result.receipt is not None
    assert result.receipt.outcome == "authoritative_non_effect"
    assert result.receipt.remove_effect == "authoritative_non_effect"
    assert result.receipt.add_effect == "authoritative_non_effect"
    assert effects.execute_calls == []
    assert journal.entry.active_scope is None


async def test_partial_recovery_prepare_is_durable_idempotent_and_keeps_scope_held():
    journal = MemoryJournal()
    cmd = command()
    effects = Effects(response=unknown_receipt(cmd))
    effects.journal = journal
    service = WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW)
    initial = await service.submit(cmd)
    assert initial.phase == "outcome_unknown"
    child = "33333333-3333-4333-8333-333333333333"

    prepared = await service.prepare_partial_recovery(str(OPERATION_ID), recovery_client_flow_id=child)
    repeated = await service.prepare_partial_recovery(str(OPERATION_ID), recovery_client_flow_id=child)

    assert prepared.schema_version == 2
    assert prepared.phase == "outcome_unknown"
    assert prepared.last_code == "partial_recovery_prepared"
    assert prepared.pending_action == "switch"
    assert prepared.receipt == initial.receipt
    assert prepared.recovery is not None
    assert str(prepared.recovery.client_flow_id) == child
    assert str(prepared.recovery.parent_client_flow_id) == str(OPERATION_ID)
    assert prepared.recovery.original == cmd.mutation.outgoing
    assert prepared.recovery.failed_target == cmd.mutation.incoming
    assert prepared.recovery.phase == "prepared"
    assert repeated.recovery == prepared.recovery
    assert journal.entry.active_scope == "member-switch"
    assert journal.entry.pending_action == "switch"
    assert journal.events.count("save_pending") == 3  # effect-pending + unknown receipt + recovery prepare

    with pytest.raises(MembershipMutationError, match="partial_recovery_attempt_conflict"):
        await service.prepare_partial_recovery(
            str(OPERATION_ID),
            recovery_client_flow_id="44444444-4444-4444-8444-444444444444",
        )


async def test_partial_recovery_completion_requires_both_effect_proofs_and_only_then_releases_scope():
    journal = MemoryJournal()
    cmd = command()
    effects = Effects(response=unknown_receipt(cmd))
    effects.journal = journal
    service = WorkspaceMembershipMutationService(journal, PermitAdmission(), effects, clock=lambda: NOW)
    await service.submit(cmd)
    child = "33333333-3333-4333-8333-333333333333"
    await service.prepare_partial_recovery(str(OPERATION_ID), recovery_client_flow_id=child)

    with pytest.raises(MembershipMutationError, match="partial_recovery_completion_unconfirmed"):
        await service.complete_partial_recovery(
            str(OPERATION_ID),
            recovery_client_flow_id=child,
            companion_operation_id="recovery-child",
            cleanup_confirmed=True,
            restoration_confirmed=False,
        )
    assert journal.entry.active_scope == "member-switch"
    assert journal.entry.pending_action == "switch"

    recovered = await service.complete_partial_recovery(
        str(OPERATION_ID),
        recovery_client_flow_id=child,
        companion_operation_id="recovery-child",
        cleanup_confirmed=True,
        restoration_confirmed=True,
    )

    assert recovered.schema_version == 2
    assert recovered.phase == "recovered"
    assert recovered.last_code == "partial_effect_recovered"
    assert recovered.pending_action is None
    assert recovered.receipt is not None and recovered.receipt.outcome == "outcome_unknown"
    assert recovered.recovery is not None and recovered.recovery.phase == "completed"
    assert recovered.recovery.cleanup_confirmed is True
    assert recovered.recovery.restoration_confirmed is True
    assert recovered.recovery.companion_operation_id == "recovery-child"
    assert journal.entry.active_scope is None

    repeated = await service.complete_partial_recovery(
        str(OPERATION_ID),
        recovery_client_flow_id=child,
        companion_operation_id="recovery-child",
        cleanup_confirmed=True,
        restoration_confirmed=True,
    )
    assert repeated.phase == "recovered"


def test_mutation_shapes_reject_ambiguous_add_remove_switch_requests():
    with pytest.raises(ValidationError):
        MembershipMutationSpec(
            action="add",
            workspace_id="w",
            workspace_account_id="wa",
            catalog_fingerprint="a" * 64,
            incoming=member("incoming"),
            outgoing=member("outgoing"),
        )
    with pytest.raises(ValidationError):
        MembershipMutationSpec(
            action="switch",
            workspace_id="w",
            workspace_account_id="wa",
            catalog_fingerprint="a" * 64,
            incoming=member("same"),
            outgoing=member("same"),
        )
