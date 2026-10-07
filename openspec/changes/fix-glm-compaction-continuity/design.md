## Context

The active Beta source model advertises a 262,144-token context window and a
32,768-token maximum output budget. Codex marks Compact work through
`x-codex-turn-metadata.request_kind=compaction`; the upstream GLM reasoning
tokens and final summary share the generation budget.

Source request shaping already applies API-key reasoning controls and operator
`source_request_overrides` before the GLM compatibility profile is applied.
Therefore a GLM profile that blindly writes `32768` and `low` can raise a
lower operator cap or overwrite an API-key policy.

## Goals / Non-Goals

**Goals**

- Give qualified GLM compaction the largest safe output budget up to 32,768.
- Keep the operationally selected `low` reasoning default for Compact.
- Preserve lower source/operator output ceilings and API-key reasoning policy.
- Preserve normal GLM and non-GLM behavior.
- Prove that source `response.incomplete` is transported as an upstream
  terminal, not fabricated by proxy disconnect handling.

**Non-Goals**

- Raising the GLM serving ceiling above 32,768.
- Changing the advertised 262,144-token context window.
- Rewriting Codex's compaction prompt or changing subscription-account Compact.
- Hiding a genuine upstream `response.incomplete(max_output_tokens)` as
  success.

## Decisions

### Compose output limits with the most restrictive positive ceiling

The qualified GLM compaction budget starts at 32,768 and is reduced by a lower
enabled model-source `max_output_tokens` and then by a lower positive
`source_request_overrides.max_output_tokens`. Invalid/non-positive override
values do not become limits here; normal request-override validation remains
responsible for their contract.

This prevents a source-specific compatibility default from raising an
operator-selected or backend-declared ceiling.

### Low reasoning is a default, not an enforcement mechanism

When no API-key reasoning policy is active, GLM Compact uses
`reasoning.effort=low`. This is intentionally lower than the earlier
`medium` profile because the observed failure exhausts the shared reasoning
and summary generation budget.

If an API key has either `enforcedReasoningEffort` or
`allowedReasoningEfforts`, source shaping remains authoritative and the GLM
profile does not rewrite the reasoning object. This preserves both enforced
effort and allowlist omitted-effort semantics.

### Keep genuine incomplete terminals observable

The model-source stream classifier already treats `response.incomplete` as a
success-class terminal for transport ownership/settlement while preserving its
terminal kind as `incomplete`. The public source stream forwards that
terminal. The fix therefore targets the request budget that causes the
upstream incomplete result; it does not translate incomplete into completed.

## Risks / Trade-offs

- **Low reasoning may reduce compaction reasoning depth.** → It is limited to
  GLM `request_kind=compaction`; ordinary GLM turns retain their requested
  effort.
- **An operator cap below 32,768 may still lead to an incomplete Compact.** →
  The operator cap is intentional authority and must not be silently raised.
- **An API-key policy may leave less output room than the default profile.** →
  Authorization policy has higher precedence than compatibility tuning.
- **A future source raises its output ceiling.** → The compatibility default
  remains 32,768 until validated separately; this change does not infer higher
  safety from a larger context window.

## Migration Plan

No data/schema migration is required.

1. Validate helper, routed source, API-key, forwarding, and stream terminal
   regressions.
2. Build and deploy the exact commit only to Beta on port 2456.
3. Exercise a source-routed GLM compaction request against the live
   DGX+edgeXpert source and inspect its terminal.
4. Promote to stable only after the live Compact returns a completed terminal
   without normal/non-GLM regressions.
