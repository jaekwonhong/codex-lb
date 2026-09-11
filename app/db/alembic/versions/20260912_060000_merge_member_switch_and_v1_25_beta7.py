"""Merge the local member-switch branch with the v1.25.0-beta.7 migration head.

Both branches are additive and may already be applied independently. This
no-op merge preserves each lineage while restoring the single-head invariant
required by startup migration validation.
"""

from __future__ import annotations

revision = "20260912_060000_merge_member_switch_and_v1_25_beta7"
down_revision = (
    "20260906_010000_add_member_switch_control",
    "20260910_000000_request_logs_missing_cost_index",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
