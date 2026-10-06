from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.workspace_member_controller.persistence import (
    MembershipOperationJournalReader,
    MembershipOperationJournalRecord,
    WorkspaceIntentReader,
    WorkspaceIntentRecord,
)

_ACTIVE_SCOPE = "member-switch"
REQUIRED_CONTROLLER_TABLES = frozenset(
    {
        "member_switch_control_records",
        "member_switch_command_receipts",
        "member_rotation_workspace_controls",
        "member_rotation_quota_operations",
        "workspace_member_usage_reset_invalidations",
        "workspace_member_final_usage_snapshots",
    }
)
_REQUIRED_COLUMNS = {
    "member_switch_control_records": {
        "id",
        "kind",
        "active_scope",
        "revision",
        "payload",
        "pending_action",
        "command_id",
        "command_hash",
    },
    "member_switch_command_receipts": {"record_id", "command_id", "fingerprint"},
    "member_rotation_workspace_controls": {
        "workspace_id",
        "workspace_account_id",
        "automatic_rotation_enabled",
        "version",
        "updated_at",
    },
    "member_rotation_quota_operations": {
        "operation_id",
        "workspace_id",
        "workspace_account_id",
        "rotation_event_id",
        "requested_at",
        "initial_admission_code",
        "reserved_at",
        "remove_effect",
        "invite_effect",
        "completed_at",
        "reservation_released_at",
    },
}


async def validate_controller_schema(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        names, columns = await connection.run_sync(_schema_snapshot)
    missing = sorted(REQUIRED_CONTROLLER_TABLES - names)
    if missing:
        raise RuntimeError("controller_schema_missing:" + ",".join(missing))
    for table, required in _REQUIRED_COLUMNS.items():
        missing_columns = sorted(required - columns.get(table, set()))
        if missing_columns:
            raise RuntimeError(f"controller_schema_columns_missing:{table}:" + ",".join(missing_columns))


def _schema_snapshot(connection) -> tuple[set[str], dict[str, set[str]]]:
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    columns = {
        table: {str(column["name"]) for column in inspector.get_columns(table)}
        for table in _REQUIRED_COLUMNS
        if table in names
    }
    return names, columns


class SqlWorkspaceIntentReader(WorkspaceIntentReader):
    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def get(self, *, workspace_id: str, workspace_account_id: str) -> WorkspaceIntentRecord:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT workspace_id, workspace_account_id, automatic_rotation_enabled, version, updated_at "
                        "FROM member_rotation_workspace_controls WHERE workspace_id = :workspace_id"
                    ),
                    {"workspace_id": workspace_id},
                )
            ).mappings().one_or_none()
        if row is None:
            return WorkspaceIntentRecord(workspace_id, workspace_account_id, False, 0, None)
        if row["workspace_account_id"] != workspace_account_id:
            raise RuntimeError("workspace_intent_identity_mismatch")
        return WorkspaceIntentRecord(
            workspace_id=str(row["workspace_id"]),
            workspace_account_id=str(row["workspace_account_id"]),
            enabled=bool(row["automatic_rotation_enabled"]),
            version=int(row["version"]),
            updated_at=_datetime_or_none(row["updated_at"]),
        )


class SqlMembershipOperationJournalReader(MembershipOperationJournalReader):
    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def active(self) -> MembershipOperationJournalRecord | None:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, kind, active_scope, revision, pending_action, command_id "
                        "FROM member_switch_control_records WHERE active_scope = :scope LIMIT 2"
                    ),
                    {"scope": _ACTIVE_SCOPE},
                )
            ).mappings().all()
        if len(rows) > 1:
            raise RuntimeError("membership_active_operation_ambiguous")
        return None if not rows else _operation(rows[0])

    async def get(self, operation_id: str) -> MembershipOperationJournalRecord | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id, kind, active_scope, revision, pending_action, command_id "
                        "FROM member_switch_control_records WHERE id = :operation_id"
                    ),
                    {"operation_id": operation_id},
                )
            ).mappings().one_or_none()
        return None if row is None else _operation(row)


def _operation(row) -> MembershipOperationJournalRecord:
    return MembershipOperationJournalRecord(
        operation_id=str(row["id"]),
        kind=str(row["kind"]),
        active_scope=None if row["active_scope"] is None else str(row["active_scope"]),
        revision=int(row["revision"]),
        pending_action=None if row["pending_action"] is None else str(row["pending_action"]),
        command_id=None if row["command_id"] is None else str(row["command_id"]),
    )


def _datetime_or_none(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise RuntimeError("controller_database_datetime_invalid")
