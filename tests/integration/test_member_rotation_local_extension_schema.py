from __future__ import annotations

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from anyio import to_thread
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.migrate import (
    _LOCAL_EXTENSION_CONSTRAINT_DEFINITION_ALIASES,
    _LOCAL_EXTENSION_CONSTRAINTS,
    _LOCAL_EXTENSION_STANDALONE_INDEXES,
    _LOCAL_EXTENSION_TABLES,
    _build_alembic_config,
    _expected_postgresql_collation,
    _expected_postgresql_format_type,
    _normalize_local_extension_constraint_definition,
    _normalize_postgresql_default,
    check_local_extension_schema,
    check_schema_drift,
    run_upgrade,
)
from app.db.models import Base

pytestmark = pytest.mark.integration

OFFICIAL_HEAD = "20260913_000000_add_oidc_provider_flow"
ROTATION_EXTENSION_TABLES = {
    "member_rotation_quota_operations",
    "member_rotation_workspace_controls",
    "workspace_member_usage_reset_invalidations",
    "workspace_member_final_usage_snapshots",
}


def test_rotation_tables_do_not_advance_official_alembic_head(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'member-rotation-official-head.sqlite'}"
    config = _build_alembic_config(db_url)
    assert ScriptDirectory.from_config(config).get_current_head() == OFFICIAL_HEAD


def test_constraint_normalization_accepts_all_exact_pg_dump_aliases() -> None:
    expected_keys = {
        ("member_rotation_quota_operations", "c", "ck_member_rotation_quota_invite_effect"),
        ("member_rotation_quota_operations", "c", "ck_member_rotation_quota_remove_effect"),
        (
            "workspace_member_final_usage_snapshots",
            "c",
            "ck_workspace_member_final_usage_snapshot_logical_window",
        ),
    }
    assert set(_LOCAL_EXTENSION_CONSTRAINT_DEFINITION_ALIASES) == expected_keys
    for key, (production, restored) in _LOCAL_EXTENSION_CONSTRAINT_DEFINITION_ALIASES.items():
        canonical = _normalize_local_extension_constraint_definition(*key, production)
        assert canonical == production
        assert _normalize_local_extension_constraint_definition(*key, restored) == canonical


def test_constraint_normalization_rejects_non_alias_changes() -> None:
    key = ("member_rotation_quota_operations", "c", "ck_member_rotation_quota_invite_effect")
    production, restored = _LOCAL_EXTENSION_CONSTRAINT_DEFINITION_ALIASES[key]
    canonical = _normalize_local_extension_constraint_definition(*key, production)

    mutations = (
        restored.replace("invite_effect", "remove_effect"),
        restored.replace("'unknown'", "'other'"),
        restored.replace(" = ANY ", " <> ALL "),
        restored.replace(", ('unknown'::character varying)::text", ""),
    )
    for mutated in mutations:
        assert _normalize_local_extension_constraint_definition(*key, mutated) != canonical

    for wrong_key in (
        ("member_rotation_workspace_controls", key[1], key[2]),
        (key[0], "u", key[2]),
        (key[0], key[1], "some_other_check"),
    ):
        assert _normalize_local_extension_constraint_definition(*wrong_key, restored) != canonical


def test_runtime_local_extension_contract_pins_exact_postgresql_physical_semantics() -> None:
    quota = Base.metadata.tables["member_rotation_quota_operations"]
    snapshots = Base.metadata.tables["workspace_member_final_usage_snapshots"]
    controls = Base.metadata.tables["member_switch_control_records"]

    assert _expected_postgresql_format_type(quota.c.requested_at) == "timestamp without time zone"
    assert _expected_postgresql_format_type(quota.c.workspace_id) == "character varying"
    assert _expected_postgresql_format_type(snapshots.c.used_percent) == "double precision"
    assert _expected_postgresql_format_type(snapshots.c.reset_at) == "bigint"
    assert _expected_postgresql_format_type(controls.c.payload) == "text"
    assert _expected_postgresql_collation(quota.c.workspace_id) == "pg_catalog.default"
    assert _expected_postgresql_collation(quota.c.requested_at) is None
    assert _normalize_postgresql_default("'not_attempted'::character varying") == "not_attempted"
    assert _normalize_postgresql_default("'NOT_ATTEMPTED'::character varying") == "NOT_ATTEMPTED"
    assert _normalize_postgresql_default("'not_attempted::text'::character varying") == "not_attempted::text"
    assert _normalize_postgresql_default("'not_attempted::INTEGER'::text") == "not_attempted::INTEGER"
    assert _normalize_postgresql_default("'not_attempted '::character varying") == "not_attempted "
    assert _normalize_postgresql_default("' not_attempted'::text") == " not_attempted"
    assert _normalize_postgresql_default("'not_attempted  '::text") == "not_attempted  "

    assert any(
        item[2] == "uq_member_rotation_quota_rotation_event"
        and item[3] == "UNIQUE (rotation_event_id)"
        and item[4:] == (True, False, False)
        for item in _LOCAL_EXTENSION_CONSTRAINTS
    )
    assert any(
        item[1] == "ix_member_rotation_quota_workspace_reserved"
        and item[2] == "btree"
        and " WHERE " not in item[3]
        and item[4:] == (False, True, True)
        for item in _LOCAL_EXTENSION_STANDALONE_INDEXES
    )


@pytest.mark.asyncio
async def test_rotation_tables_are_beta_local_extensions_outside_alembic_lineage(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'member-rotation-local-extension.sqlite'}"
    result = await to_thread.run_sync(lambda: run_upgrade(db_url, "head", bootstrap_legacy=False))
    assert result.current_revision == OFFICIAL_HEAD
    assert ROTATION_EXTENSION_TABLES <= _LOCAL_EXTENSION_TABLES

    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as connection:
            tables_before = await connection.run_sync(lambda sync: set(sa_inspect(sync).get_table_names()))
        assert ROTATION_EXTENSION_TABLES.isdisjoint(tables_before)

        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(
                    sync,
                    tables=[Base.metadata.tables[name] for name in sorted(ROTATION_EXTENSION_TABLES)],
                    checkfirst=False,
                )
            )

        async with engine.connect() as connection:
            tables_after = await connection.run_sync(lambda sync: set(sa_inspect(sync).get_table_names()))
        assert ROTATION_EXTENSION_TABLES <= tables_after
    finally:
        await engine.dispose()

    assert await to_thread.run_sync(lambda: check_schema_drift(db_url)) == ()
    # Runtime startup enforces this contract on PostgreSQL. SQLite is not a
    # dual-lane production backend, so the runtime extension fence is inert.
    assert await to_thread.run_sync(lambda: check_local_extension_schema(db_url)) == ()
