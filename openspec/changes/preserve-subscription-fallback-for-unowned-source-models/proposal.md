# Preserve subscription fallback for unowned source models

## Why

A source-scoped API key can intentionally combine a private model source with ordinary ChatGPT subscription models. The current HTTP Responses fail-closed guard treats any model absent from the process model registry as source-only. That is not a valid ownership signal: the shared registry can be cleared when no account is currently `active`, and a genuine upstream subscription model such as `gpt-6-astra` can also be absent from the static bootstrap floor.

In production this caused `/backend-api/codex/responses` HTTP fallback for `gpt-6-astra` to return `model_source_unavailable` on the edge-scoped gateway key even though the assigned DGX Spark + MSI edgeXpert source only declares `glm5.3-flash`. The same Astra turns routed successfully over WebSocket to subscription accounts, proving the model was not owned by the assigned source.

The serving topology is a single OpenAI-compatible model-source endpoint backed
by TensorFold tensor parallelism: DGX Spark runs rank 0 and the head API, while
MSI edgeXpert runs rank 1 as the worker. The two machines are therefore one
distributed model instance from Codex LB's routing perspective, not two
independent sources that require Codex LB load balancing or failover.

## What Changes

- Treat assigned-source model ownership, not model-registry absence by itself, as the final provider-boundary signal after normal and disabled Responses source lookup miss.
- Preserve fail-closed behavior when the assigned edge-cluster source actually declares the model but cannot route it.
- Preserve the historical fail-closed boundary for a source-scoped key whose assignment rows disappear and therefore has no source identity left to prove safe fallback for an unknown slug.
- Do not reapply the source-only guard when a structural source-route exclusion (for example a file pin or Codex terminal compaction) already requires subscription routing, or when the existing continuity resolver has already suppressed an enabled source candidate in favor of a recorded `previous_response_id` subscription owner.
- Keep exact API-key model allowlisting consistent with ordinary source selection when evaluating source ownership.
- Keep the `glm5.3-flash` encrypted-reasoning replay adaptation independent of a specific model-source row id so the single edge-cluster source can be recreated or moved without losing the compatibility scrub.

No schema, migration, setting, or member-rotation behavior changes.

## Capabilities

### Modified Capabilities

- `model-source-routing`: source-scoped Responses fallback now requires positive assigned-source ownership before failing closed on a registry-missing model, while preserving structural subscription routes, continuity ownership, and dangling-scope fail-closed behavior.

## Impact

- Code: `app/modules/model_sources/{repository,selection}.py` and the two Responses HTTP handlers in `app/modules/proxy/api.py`.
- Tests: route-level regressions for backend/v1 Responses, edge runtime-enabled routing, source-id-independent `glm5.3-flash` replay adaptation, structural file-pin routing, and continuity-suppressed subscription ownership.
- Qualification: `scripts/qualify_beta_patch_packet.sh` is the canonical semantic/regression entrypoint and is invoked by the Q2 qualification wrapper so future local Beta rebases cannot silently skip this contract.
- Runtime: Beta app image only. No database or configuration mutation is required; the existing Beta image remains an app-level rollback authority.
