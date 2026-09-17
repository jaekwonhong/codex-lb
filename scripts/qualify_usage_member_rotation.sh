#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

"${repo_root}/scripts/qualify_beta_patch_packet.sh"

uv run pytest -q \
  tests/unit/test_weekly_usage_observation.py \
  tests/unit/test_rotation_reset_credit_resolution.py \
  tests/unit/test_member_rotation_quota_history.py \
  tests/unit/test_member_rotation_foundation_integration.py \
  tests/unit/test_member_usage_snapshot_repository.py \
  tests/unit/test_member_rotation_controller.py \
  tests/unit/test_member_switch_control.py \
  tests/unit/test_member_switch_continuation.py \
  tests/unit/test_member_rotation_beta9_candidate_gate.py \
  tests/unit/test_member_rotation_p7_qualification.py \
  tests/integration/test_member_rotation_local_extension_schema.py \
  tests/integration/test_member_rotation_operator_api.py \
  tests/integration/test_member_rotation_g2_operator_adapter.py

uv run ruff check \
  app/modules/member_switch/rotation_controller.py \
  app/modules/member_rotation_operator/adapter.py \
  app/db/migrate.py \
  app/db/session.py \
  scripts/member_rotation_beta9_candidate_gate.py \
  scripts/member_rotation_release_qualification.py \
  tests/unit/test_member_rotation_beta9_candidate_gate.py \
  tests/integration/test_member_rotation_local_extension_schema.py \
  tests/unit/test_member_rotation_p7_qualification.py \
  tests/unit/test_member_rotation_controller.py \
  tests/integration/test_member_rotation_g2_operator_adapter.py

uv run ty check \
  app/modules/member_switch/rotation_controller.py \
  app/modules/member_rotation_operator/adapter.py \
  app/db/migrate.py \
  app/db/session.py \
  scripts/member_rotation_beta9_candidate_gate.py \
  scripts/member_rotation_release_qualification.py \
  tests/unit/test_member_rotation_beta9_candidate_gate.py \
  tests/unit/test_member_rotation_p7_qualification.py \
  tests/unit/test_member_rotation_controller.py \
  tests/integration/test_member_rotation_g2_operator_adapter.py

npx --yes @fission-ai/openspec@1.11.0 validate --type change --strict --no-interactive -- usage-driven-business-member-rotation

if [[ "${1:-}" == "--with-p4" ]]; then
  : "${P4_ARTIFACT:?P4_ARTIFACT is required with --with-p4}"
  : "${P4_MANIFEST:?P4_MANIFEST is required with --with-p4}"
  : "${P4_OPS_WORKTREE:?P4_OPS_WORKTREE is required with --with-p4}"
  : "${P4_BASE_SOURCE:?P4_BASE_SOURCE is required with --with-p4}"
  : "${P4_SCRATCH_ROOT:?P4_SCRATCH_ROOT is required with --with-p4}"
  mkdir -p "${P4_SCRATCH_ROOT}"
  uv run python -m scripts.member_rotation_release_qualification p4 \
    --artifact "${P4_ARTIFACT}" \
    --manifest "${P4_MANIFEST}" \
    --ops-worktree "${P4_OPS_WORKTREE}" \
    --base-source "${P4_BASE_SOURCE}" \
    --scratch-root "${P4_SCRATCH_ROOT}"
fi
