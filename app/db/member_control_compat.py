"""Bounded legacy replay compatibility; the merged migration stays immutable."""

from __future__ import annotations

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

CONTROL_REVISION = "20260906_010000_add_member_switch_control"
CONTROL_PARENT = "20260816_000000_add_model_source_embeddings"


def _tables() -> tuple[sa.Table, sa.Table]:
    # Frozen contract for this exact historical boundary, not live ORM metadata.
    metadata = sa.MetaData()
    controls = sa.Table(
        "member_switch_control_records",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("active_scope", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("pending_action", sa.String(), nullable=True),
        sa.Column("command_id", sa.String(), nullable=True),
        sa.Column("command_hash", sa.String(), nullable=True),
        sa.UniqueConstraint("active_scope"),
        sa.CheckConstraint("revision >= 0", name="ck_member_switch_revision"),
    )
    receipts = sa.Table(
        "member_switch_command_receipts",
        metadata,
        sa.Column("record_id", sa.String(), sa.ForeignKey("member_switch_control_records.id"), primary_key=True),
        sa.Column("command_id", sa.String(), primary_key=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
    )
    return controls, receipts


def _validate_existing(inspector: sa.Inspector, expected: sa.Table) -> None:
    name = expected.name
    columns = {item["name"]: item for item in inspector.get_columns(name)}
    dialect = inspector.bind.dialect
    if set(columns) != set(expected.columns.keys()) or any(
        str(columns[column.name]["type"].compile(dialect=dialect)).upper()
        != str(column.type.compile(dialect=dialect)).upper()
        or columns[column.name]["nullable"] != column.nullable
        or columns[column.name].get("default") is not None
        for column in expected.columns
    ):
        raise RuntimeError(f"incompatible_member_control_schema:{name}:columns")
    if inspector.get_pk_constraint(name)["constrained_columns"] != list(expected.primary_key.columns.keys()):
        raise RuntimeError(f"incompatible_member_control_schema:{name}:primary_key")
    unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
    checks = {
        "".join(item["sqltext"].lower().translate(str.maketrans("", "", '()"')).split())
        for item in inspector.get_check_constraints(name)
    }
    foreign = inspector.get_foreign_keys(name)
    if name == "member_switch_control_records":
        if unique != {("active_scope",)} or checks != {"revision>=0"} or foreign:
            raise RuntimeError(f"incompatible_member_control_schema:{name}:admission_constraints")
    else:
        valid_reference = len(foreign) == 1 and (
            foreign[0]["constrained_columns"] == ["record_id"]
            and foreign[0]["referred_table"] == "member_switch_control_records"
            and foreign[0]["referred_columns"] == ["id"]
            and foreign[0].get("referred_schema") in {None, inspector.default_schema_name}
            and foreign[0].get("options", {}).get("ondelete", "NO ACTION") == "NO ACTION"
            and foreign[0].get("options", {}).get("onupdate", "NO ACTION") == "NO ACTION"
        )
        if unique or checks or not valid_reference:
            raise RuntimeError(f"incompatible_member_control_schema:{name}:receipt_foreign_key")


def validate_existing_control_schema(connection: Connection) -> bool:
    """Read-only preflight. Return whether a materialized counterpart exists."""
    inspector = sa.inspect(connection)
    tables = _tables()
    existing = set(inspector.get_table_names())
    for table in tables:
        if table.name in existing:
            _validate_existing(inspector, table)
    controls, receipts = tables
    if receipts.name in existing:
        # SQLite may previously have been opened with foreign_keys disabled.
        statement = sa.select(receipts.c.record_id).limit(1)
        if controls.name in existing:
            statement = statement.where(
                ~sa.exists(sa.select(controls.c.id).where(controls.c.id == receipts.c.record_id))
            )
        if connection.execute(statement).first() is not None:
            raise RuntimeError("incompatible_member_control_schema:orphan_receipt")
    return bool(existing & {table.name for table in tables})


def adopt_control_schema_at_parent(connection: Connection, script: ScriptDirectory) -> None:
    """Create missing counterparts and record exactly one proven revision.

    The caller owns both the migration lock and this transaction. Earlier steps
    must have executed normally; neither their schema nor history is inferred.
    """
    context = MigrationContext.configure(connection)
    if context.get_current_heads() != (CONTROL_PARENT,):
        raise RuntimeError("member_control_replay_requires_exact_parent")
    boundary = script.get_revision(CONTROL_REVISION)
    if boundary is None or boundary.down_revision != CONTROL_PARENT:
        raise RuntimeError("member_control_replay_graph_mismatch")
    if not validate_existing_control_schema(connection):
        raise RuntimeError("member_control_replay_requires_existing_table")
    inspector = sa.inspect(connection)
    for table in _tables():
        if not inspector.has_table(table.name):
            table.create(connection)
    context.stamp(script, CONTROL_REVISION)
