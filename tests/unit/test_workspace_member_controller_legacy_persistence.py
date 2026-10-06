from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import app.modules.workspace_member_controller.legacy_persistence as legacy
from app.modules.workspace_member_controller.legacy_persistence import (
    LegacyMembershipOperationJournalReader,
    LegacyWorkspaceIntentReader,
)

pytestmark = pytest.mark.unit


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@dataclass
class Intent:
    workspace_id: str = "workspace-1"
    workspace_account_id: str = "workspace-account-1"
    enabled: bool = True
    version: int = 5
    updated_at: datetime = NOW


async def test_legacy_workspace_intent_reader_hides_operator_repository_shape(monkeypatch):
    class FakeRepository:
        def __init__(self, _session):
            pass

        async def intent(self, *, workspace_id: str, workspace_account_id: str):
            assert workspace_id == "workspace-1"
            assert workspace_account_id == "workspace-account-1"
            return Intent()

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(legacy, "MemberRotationOperatorRepository", FakeRepository)
    record = await LegacyWorkspaceIntentReader(sessions).get(
        workspace_id="workspace-1",
        workspace_account_id="workspace-account-1",
    )
    assert record.workspace_id == "workspace-1"
    assert record.enabled is True
    assert record.version == 5
    assert record.updated_at == NOW


async def test_legacy_operation_reader_exposes_only_controller_journal_fields():
    class Record:
        id = "run-1"
        kind = "run"
        active_scope = "member-switch"
        revision = 3
        payload = '{"secret":"must-not-leak"}'
        pending_action = "remove_member"
        command_id = "cmd-1"
        command_hash = "hidden-hash"

    class Controls:
        async def active(self):
            return Record()

        async def get(self, operation_id: str):
            return Record() if operation_id == "run-1" else None

    reader = LegacyMembershipOperationJournalReader(Controls())  # type: ignore[arg-type]
    active = await reader.active()
    assert active is not None
    assert active.operation_id == "run-1"
    assert active.command_id == "cmd-1"
    assert not hasattr(active, "payload")
    assert not hasattr(active, "command_hash")
