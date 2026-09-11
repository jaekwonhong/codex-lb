"""Persist member-switch admission, state and command receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_010000_add_member_switch_control"
down_revision = "20260816_000000_add_model_source_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_switch_control_records",
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
    op.create_table(
        "member_switch_command_receipts",
        sa.Column("record_id", sa.String(), sa.ForeignKey("member_switch_control_records.id"), primary_key=True),
        sa.Column("command_id", sa.String(), primary_key=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("member_switch_command_receipts")
    op.drop_table("member_switch_control_records")
