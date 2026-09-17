from __future__ import annotations

from pathlib import Path


def test_beta_patch_packet_wrapper_runs_semantic_guard_and_regressions() -> None:
    text = Path("scripts/qualify_beta_patch_packet.sh").read_text(encoding="utf-8")

    assert "python3 -m scripts.verify_beta_patch_packet --root ." in text
    assert "tests/unit/test_verify_beta_patch_packet.py" in text
    assert "tests/unit/test_model_source_selection_scope.py" in text
    assert "scoped_key_registry_miss_for_unowned_subscription_model_falls_through" in text
    assert "deleted_assigned_source_keeps_registry_miss_fail_closed" in text


def test_q2_qualification_cannot_skip_beta_patch_packet_contract() -> None:
    text = Path("scripts/qualify_usage_member_rotation.sh").read_text(encoding="utf-8")

    assert '"${repo_root}/scripts/qualify_beta_patch_packet.sh"' in text
