# Verification: GLM5.3-flash Compact continuity

Date: 2026-10-07

## Candidate identity

- Branch: `fix/production-beta-astra-local-history-auto-recovery-20261007`
- Runtime commit: `e9cca2448`
- GLM policy commit: `0f9f9fdba`
- Beta image: `codex-lb-beta:production-beta-e9cca2448-20261007`
- Beta port: `2456`
- Rollback image/container retained separately.

The active source is `dgx-msi-glm5.3-flash` with Responses enabled,
`context_window=262144`, `max_output_tokens=32768`, and supported
reasoning levels `low`, `medium`, and `high`.

## Automated validation

- GLM compaction/profile/model-source regressions: 42 passed.
- Ruff check: passed.
- Ruff format check: passed.
- Changed-file type check: passed.
- OpenSpec strict validation for this change: passed.
- The stream compatibility regression preserves a genuine upstream
  `response.incomplete(max_output_tokens)` terminal instead of fabricating
  completion.

## Live Beta validation

### Small Compact smoke

An authenticated source-routed request to
`/backend-api/codex/responses` with
`x-codex-turn-metadata.request_kind=compaction` and client
`reasoning.effort=high` completed successfully:

- HTTP: 200
- terminal: `response.completed`
- elapsed: 1.98 s
- input tokens: 124
- output tokens: 18
- reasoning tokens: 7
- `incomplete_details`: none

### Long-history Compact

A synthetic full-history request of 184,094 bytes exercised the same live
Beta source route:

- HTTP: 200
- terminal: `response.completed`
- elapsed: 49.58 s
- input tokens: 31,866
- output tokens: 373
- reasoning tokens: 12
- total tokens: 32,239
- `incomplete_details`: none

The request log records `reasoning_effort=low`, proving that the Compact-only
profile was applied.

For comparison, an earlier live GLM request in the same runtime database
recorded 117,999 input tokens, 32,768 output tokens, 32,768 reasoning tokens,
and `reasoning_effort=high`. That is the budget-exhaustion shape this change
is intended to avoid.

### Normal GLM regression

A live non-compaction GLM request carrying `reasoning.effort=high` completed:

- HTTP: 200
- terminal: `response.completed`
- elapsed: 2.10 s
- input tokens: 25
- output tokens: 41
- reasoning tokens: 34
- request log `reasoning_effort=high`

This confirms the low-reasoning profile is scoped to Compact and does not
rewrite ordinary GLM turns.

## Decision

The Beta candidate satisfies the acceptance criteria for the GLM Compact fix:
the live long-history Compact completes without
`response.incomplete(reason=max_output_tokens)`, the source/output ceilings
remain bounded, and ordinary GLM reasoning remains unchanged.

Status: **stable candidate**. This record does not promote the image to the
stable port by itself.
