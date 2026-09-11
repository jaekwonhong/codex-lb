from __future__ import annotations

import hashlib
from importlib import import_module
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.member_control_compat import CONTROL_PARENT, CONTROL_REVISION
from app.db.migrate import current_revision, run_upgrade

pytestmark = pytest.mark.integration


def _database(tmp_path: Path) -> tuple[str, sa.Engine]:
    path = tmp_path / "migration.sqlite"
    url = f"sqlite+aiosqlite:///{path}"
    run_upgrade(url, CONTROL_PARENT, bootstrap_legacy=False)
    return url, sa.create_engine(f"sqlite:///{path}")


@pytest.mark.parametrize("missing", [None, "receipts", "controls"])
def test_runner_preserves_existing_counterparts(tmp_path, monkeypatch, missing):
    url, engine = _database(tmp_path)
    migration = import_module(f"app.db.alembic.versions.{CONTROL_REVISION}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            if missing == "controls":
                connection.execute(sa.text("DROP TABLE member_switch_control_records"))
            else:
                connection.execute(
                    sa.text(
                        "INSERT INTO member_switch_control_records (id,kind,active_scope,revision,payload) "
                        "VALUES ('retained','run','member-switch',8,'evidence')"
                    )
                )
            if missing == "receipts":
                connection.execute(sa.text("DROP TABLE member_switch_command_receipts"))
            elif missing is None:
                connection.execute(
                    sa.text("INSERT INTO member_switch_command_receipts VALUES ('retained','command','fingerprint')")
                )
        assert run_upgrade(url, "head", bootstrap_legacy=False).current_revision == CONTROL_REVISION
        assert run_upgrade(url, "head", bootstrap_legacy=False).current_revision == CONTROL_REVISION
        with engine.connect() as connection:
            controls = connection.execute(
                sa.text("SELECT id,revision,payload FROM member_switch_control_records")
            ).all()
            assert controls == ([] if missing == "controls" else [("retained", 8, "evidence")])
            receipts = connection.execute(sa.text("SELECT * FROM member_switch_command_receipts")).all()
            assert receipts == ([("retained", "command", "fingerprint")] if missing is None else [])
    finally:
        engine.dispose()


@pytest.mark.parametrize("defect", ["uniqueness", "revision", "column", "nullable", "foreign_key", "default"])
def test_runner_rejects_bad_counterpart_without_advancing_revision(tmp_path, defect):
    url, engine = _database(tmp_path)
    try:
        with engine.begin() as connection:
            if defect == "foreign_key":
                connection.execute(
                    sa.text(
                        "CREATE TABLE member_switch_command_receipts (record_id VARCHAR NOT NULL, "
                        "command_id VARCHAR NOT NULL, fingerprint VARCHAR NOT NULL, PRIMARY KEY(record_id,command_id))"
                    )
                )
            else:
                unique = "" if defect == "uniqueness" else ", UNIQUE(active_scope)"
                check = "" if defect == "revision" else ", CHECK(revision >= 0)"
                payload_type = "INTEGER" if defect == "column" else "TEXT"
                kind_null = "" if defect == "nullable" else "NOT NULL"
                default = " DEFAULT 'foreign-owner'" if defect == "default" else ""
                connection.execute(
                    sa.text(
                        "CREATE TABLE member_switch_control_records (id VARCHAR NOT NULL PRIMARY KEY, "
                        f"kind VARCHAR {kind_null}, active_scope VARCHAR{default}, revision INTEGER NOT NULL, "
                        f"payload {payload_type} NOT NULL, pending_action VARCHAR, command_id VARCHAR, "
                        f"command_hash VARCHAR {unique}{check})"
                    )
                )
            tables_before = sa.inspect(connection).get_table_names()
        with pytest.raises(RuntimeError, match="incompatible_member_control_schema"):
            run_upgrade(url, "head", bootstrap_legacy=False)
        assert current_revision(url) == CONTROL_PARENT
        with engine.connect() as connection:
            assert sa.inspect(connection).get_table_names() == tables_before
    finally:
        engine.dispose()


def test_runner_rejects_orphan_receipts_even_with_valid_foreign_key(tmp_path, monkeypatch):
    url, engine = _database(tmp_path)
    migration = import_module(f"app.db.alembic.versions.{CONTROL_REVISION}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            connection.execute(
                sa.text("INSERT INTO member_switch_command_receipts VALUES ('missing-parent','command','fingerprint')")
            )
        with pytest.raises(RuntimeError, match="orphan_receipt"):
            run_upgrade(url, "head", bootstrap_legacy=False)
        assert current_revision(url) == CONTROL_PARENT
    finally:
        engine.dispose()


def test_control_compatibility_does_not_apply_to_earlier_target(tmp_path):
    url, engine = _database(tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE member_switch_control_records (wrong INTEGER)"))
        assert run_upgrade(url, CONTROL_PARENT, bootstrap_legacy=False).current_revision == CONTROL_PARENT
        with engine.connect() as connection:
            assert not sa.inspect(connection).has_table("member_switch_command_receipts")
    finally:
        engine.dispose()


def test_original_control_migration_is_byte_identical_to_merged_revision():
    migration = import_module(f"app.db.alembic.versions.{CONTROL_REVISION}")
    assert hashlib.sha256(Path(migration.__file__).read_bytes()).hexdigest() == (
        "79556e21764c1fc96543d776428f026373634601f18ad759803bc34a36aac336"
    )


def test_relative_target_is_not_resolved_again_after_adoption(tmp_path, monkeypatch):
    url, engine = _database(tmp_path)
    migration = import_module(f"app.db.alembic.versions.{CONTROL_REVISION}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
        assert run_upgrade(url, "+1", bootstrap_legacy=False).current_revision == CONTROL_REVISION
    finally:
        engine.dispose()


def test_failed_revision_acknowledgement_rolls_back_missing_table_creation(tmp_path, monkeypatch):
    url, engine = _database(tmp_path)
    migration = import_module(f"app.db.alembic.versions.{CONTROL_REVISION}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            connection.execute(sa.text("DROP TABLE member_switch_command_receipts"))
        original = MigrationContext.stamp

        def fail_control_stamp(self, script, revision):
            if revision == CONTROL_REVISION:
                raise OSError("synthetic revision acknowledgement failure")
            return original(self, script, revision)

        with monkeypatch.context() as patch:
            patch.setattr(MigrationContext, "stamp", fail_control_stamp)
            with pytest.raises(OSError, match="synthetic revision"):
                run_upgrade(url, "head", bootstrap_legacy=False)
        assert current_revision(url) == CONTROL_PARENT
        with engine.connect() as connection:
            assert not sa.inspect(connection).has_table("member_switch_command_receipts")
        assert run_upgrade(url, "head", bootstrap_legacy=False).current_revision == CONTROL_REVISION
    finally:
        engine.dispose()
