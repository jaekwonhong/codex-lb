from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.modules.workspace_member_controller.mutation_models import MembershipMutationState


@dataclass(frozen=True, slots=True)
class WorkspaceIntentRecord:
    workspace_id: str
    workspace_account_id: str
    enabled: bool
    version: int
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class MembershipOperationJournalRecord:
    operation_id: str
    kind: str
    active_scope: str | None
    revision: int
    pending_action: str | None
    command_id: str | None


class WorkspaceIntentReader(Protocol):
    """Read Controller-owned workspace intent without exposing ORM rows."""

    async def get(self, *, workspace_id: str, workspace_account_id: str) -> WorkspaceIntentRecord: ...


class MembershipOperationJournalReader(Protocol):
    """Read durable operation ownership without exposing mutation methods."""

    async def active(self) -> MembershipOperationJournalRecord | None: ...

    async def get(self, operation_id: str) -> MembershipOperationJournalRecord | None: ...


@dataclass(frozen=True, slots=True)
class MembershipMutationJournalEntry:
    operation_id: str
    kind: str
    active_scope: str | None
    revision: int
    state: MembershipMutationState
    pending_action: str | None
    command_id: str | None


@dataclass(frozen=True, slots=True)
class MembershipMutationClaim:
    entry: MembershipMutationJournalEntry
    execute: bool


class MembershipMutationJournal(Protocol):
    """Durable no-replay journal used by membership effects.

    The implementation must commit ``claim`` before an external effect is
    invoked. Repeating a recorded command id with the same fingerprint returns
    ``execute=False``; a different fingerprint for that id fails closed.
    """

    async def get_mutation(self, operation_id: str) -> MembershipMutationJournalEntry | None: ...

    async def create_mutation(self, state: MembershipMutationState) -> MembershipMutationJournalEntry: ...

    async def claim_mutation(
        self,
        current: MembershipMutationJournalEntry,
        *,
        command_id: str,
        action: str,
        fingerprint: str,
        expected_revision: int,
    ) -> MembershipMutationClaim: ...

    async def save_mutation(
        self,
        current: MembershipMutationJournalEntry,
        state: MembershipMutationState,
        *,
        complete: bool,
        release: bool,
    ) -> MembershipMutationJournalEntry: ...
