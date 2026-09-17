#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

python3 -m scripts.verify_beta_patch_packet --root .

uv run pytest -q \
  tests/unit/test_verify_beta_patch_packet.py \
  tests/unit/test_model_source_selection_scope.py

uv run pytest -q tests/integration/test_model_source_routing.py \
  -k 'runtime_enabled_disabled_responses_source_routes_for_scoped_assigned_key or scoped_source_only_responses_miss_fails_closed_before_subscription or scoped_key_registry_miss_for_unowned_subscription_model_falls_through or deleted_assigned_source_keeps_registry_miss_fail_closed'

uv run ruff check \
  app/modules/model_sources/repository.py \
  app/modules/model_sources/selection.py \
  app/modules/proxy/api.py \
  scripts/verify_beta_patch_packet.py \
  tests/unit/test_verify_beta_patch_packet.py \
  tests/unit/test_model_source_selection_scope.py \
  tests/integration/test_model_source_routing.py

uv run ty check \
  app/modules/model_sources/repository.py \
  app/modules/model_sources/selection.py \
  app/modules/proxy/api.py \
  scripts/verify_beta_patch_packet.py
