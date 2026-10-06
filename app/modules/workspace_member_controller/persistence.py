from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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

