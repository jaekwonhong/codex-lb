from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

pytestmark = pytest.mark.unit


def test_control_schema_upgrade_constraints_and_downgrade(monkeypatch):
    migration = import_module("app.db.alembic.versions.20260906_010000_add_member_switch_control")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert set(sa.inspect(connection).get_table_names()) == {
            "member_switch_control_records",
            "member_switch_command_receipts",
        }
        connection.execute(
            sa.text(
                "INSERT INTO member_switch_control_records (id, kind, active_scope, revision, payload) "
                "VALUES ('one', 'run', 'member-switch', 0, '{}')"
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO member_switch_control_records (id, kind, active_scope, revision, payload) "
                    "VALUES ('two', 'run', 'member-switch', 0, '{}')"
                )
            )
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("UPDATE member_switch_control_records SET revision = -1 WHERE id='one'"))
        migration.downgrade()
        assert sa.inspect(connection).get_table_names() == []
        migration.upgrade()
    engine.dispose()
