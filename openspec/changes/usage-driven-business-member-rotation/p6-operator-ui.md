# P6 — UI / Operator Surface

## Boundary

P6 projects the G1 foundation and P3 local history into the Accounts member-management surface. It owns one persistent value: workspace-scoped `automatic_rotation_enabled` operator intent. The default is `false`, and reading status does not create an intent row. The P6 API has no reset-credit, remove, invite, OAuth, or controller-command endpoint.

The status path uses three sources with separate meanings:

1. G1 `RotationFoundationReadModel` is authoritative for foundation state and Weekly classification. P6 does not infer eligibility from Usage percentages.
2. P3 `RotationQuotaRepository.snapshot()` and `MemberUsageSnapshotRepository.list_history()` supply local rolling counts and immutable removed-member final Usage.
3. `RotationOperatorSnapshotAdapter` is an additive, read-only P5 integration seam for current member, 5H display evidence, controller/reset progress, next candidate, invitation-vs-membership state, Companion status, and removed-at timestamps.

The default adapter is `DurableRotationOperatorSnapshotAdapter`, which projects retained P5 controller/run evidence without invoking a controller or any effect. When no matching durable snapshot exists (or a null adapter is explicitly installed), enabled intent reports `integration_pending` / `controller_snapshot_unavailable`; the UI does not substitute Accounts Usage, telemetry, or the manual member-switch catalog as eligibility evidence.

## Intent and effect separation

`PUT /api/member-rotation/operator/workspaces/{workspace_id}/intent` stores only operator intent with an optimistic `expectedVersion` guard. Both the identity-bearing `GET /api/member-rotation/operator` status surface and the intent mutation require `accounts:write`, matching the beta.9 member-management privacy boundary. The frontend disables the operator query entirely without that permission instead of polling a forbidden endpoint. The GET remains cache-disabled and effect-free.

The ON/OFF value is displayed separately from controller runtime status. Switching intent OFF does not rewrite or hide an already-reported in-flight or attention controller state; with no controller snapshot, OFF is rendered as `disabled`.

For principals with `accounts:write`, React Query status polling is every 30 seconds with window-focus refetch disabled. Page load and polling call only the GET endpoint. Without `accounts:write`, the query is disabled and the UI shows a permission notice without fetching identity-bearing state. The switch mutation is invoked only from `onCheckedChange`, and a successful save is followed only by a read-model invalidation/refetch.

P5 must not treat this setting alone as effect authority. It still needs G1 admission, durable controller ownership, effect no-replay state, and any P4 capability/provenance gates before a membership effect.

## Display semantics

- Weekly: P6 renders G1 `weekly_state` plus `weekly_reason`. `reset_elapsed`, `stale`, missing evidence, available, and exhausted remain distinct.
- 5H: P6 can display a controller-provided observation and percentage, but that DTO is explicitly display evidence and is never converted into Weekly eligibility.
- Reset: G1 remains authoritative for resolution-required, recovered, reconciliation-pending, confirmed-no-credit, and unavailable outcomes. The adapter may supplement `redeem_in_progress` only while G1 still reports `reset_required`; an adapter cannot promote pending/unknown foundation evidence to recovered.
- Internal guard: `24H x / 3` and `7D y / 7` are labeled internal/local. No OpenAI server limit is claimed.
- Coverage: P3 remains `observed_local` with incomplete history. The UI discloses that external and pre-adoption changes may be absent.
- Removed-member history: original `reset_at` is always retained. P3 invalidation makes `effective_reset_at` null; the UI displays Original Reset separately from Effective Reset and says the original evidence is preserved.
- Effect ambiguity: unknown remove/invite effects appear as attention blockers. P6 exposes no effect retry action.
- Invitation and join: `invitation_issued` and `membership_confirmed` are separate booleans and separate labels.
- Candidate safety: the service accepts a next candidate only when it exactly matches the non-owner member catalog and additionally rejects an owner-email match. The frontend repeats the owner-email check defensively before rendering.

## P5 integration note

The public `RotationOperatorSnapshotAdapter` remains additive and read-only, with no action method. G2 now supplies a durable implementation, and P6 consumes its projected facts through this boundary. The current mappings include:

- exact current member identity;
- a display-only 5H observation;
- controller/reset progress including `redeem_in_progress` if applicable;
- validated next candidate;
- invitation-issued vs authoritative membership-confirmed state;
- Companion capability/provenance attention;
- removed-at timestamp keyed by P3 membership epoch.

Missing portions remain explicit rather than being derived locally. The current single-evaluation adapter only supplies its selected controller's removed-at mapping; multi-controller historical aggregation and explicit outgoing-evidence attribution remain separate review observations, not claims of this correction.

The operator frontend uses the canonical backend numeric-window aliases `count24H`, `limit24H`, `count168H` and `limit168H`. A successful intent write returns its committed enabled value and version; sequential writes use the version from that successful response. Wire-contract tests must feed actual backend serialization to the client, not only manually constructed component data.

Interrupted pre-start worker evaluation is surfaced as `needs_attention` with an explicit blocker, preserving quota, snapshots and the fixed evaluation binding. It never exposes an effect-replay control. The [current release notes](../../specs/member-switch-commands/off-deployment-20260920.md) distinguish deployed b98/e55 OFF evidence from subsequent undeployed correction source.
