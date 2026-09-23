# Rotation epic review corrections

## Why
The source-bound review found a missing final reset admission boundary, stale intent responses, an unresumable pre-start worker state, an incomplete scheduler test seam, and stale current-state documentation. A later independent review also reproduced rejection of valid operator responses by the frontend because numeric-window aliases differ.

## What Changes
- Revalidate rotation authority at the central reset consume boundary without changing ordinary callers or weakening durable pin/no-replay coordination.
- Surface interrupted pre-effect worker evaluations as explicit operator attention, retaining their single-evaluation identity and evidence rather than automatically resetting or dispatching again.
- Return committed intent values/versions and align the operator frontend with canonical backend wire aliases.
- Complete the scheduler test isolation seam and add actual API/wire and failure-boundary regressions.
- Update current context/epic notes to distinguish deployed b98/e55 OFF evidence from this uncommitted, undeployed correction source.

## Impact
Focused source, tests and OpenSpec documentation only. No production lifecycle/DB changes, enabled intent or plan, real reset/remove/invite, Git branch/commit/merge, rebuild or deployment. Existing sealed packets and unrelated dirty work remain preserved. Multi-controller history and evidence-owner attribution remain separately scoped observations.
