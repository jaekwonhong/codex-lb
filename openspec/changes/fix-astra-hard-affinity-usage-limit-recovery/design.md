## Context

See `proposal.md` for the incident and scope. The recovery path spans direct
HTTP streaming, direct WebSocket, HTTP bridge reconnect/replay, load-balancer
ownership selection, and durable bridge operation fencing. Those surfaces must
agree on two facts: whether quota evidence is definitive for the exact continuity
owner, and whether the request body is safe to replay on another account.

The existing `replay_relocation.decide_relocation` contract is the
transport-independent authority for the second fact. The load balancer separately
owns required-account and sticky-owner selection semantics, including generic
operator-configured account requirements that are not continuity provenance.

## Goals / Non-Goals

**Goals**

- Make shared relocation policy the only authority that can release a continuity
  owner after definitive quota exhaustion.
- Preserve owner-specific definitive quota provenance across selection,
  forwarding, and reconnect boundaries without treating advisory pressure or a
  generic rate limit as proof.
- Let HTTP-bridge full-resend relocation re-fence the existing durable operation
  on the replacement account before dispatch, then keep subsequent continuity on
  that replacement.
- Preserve the existing error/degraded-mode behavior of generic configured
  `required_account_id` routing.

**Non-Goals**

- Moving requests after downstream-visible output or other evidence that upstream
  already executed the turn.
- Relaxing file, conversation, unresolved-tool, explicit turn-state, or
  single-account ownership constraints.
- Changing ProviderSwitcher-client or introducing new persistence/schema.

## Decisions

### Cross-account movement always goes through the shared relocation verdict

Direct HTTP selection-time owner exhaustion and post-dispatch quota handling use
the same `decide_relocation` inputs as the other transport paths. A locally
verified full-resend candidate is necessary material, not relocation authority by
itself. The owner pin is cleared and the owner excluded only after a movable
verdict returns an account-neutral body.

This is preferred over transport-local checks because those checks had drifted:
one path could clear a required owner on selection failure while another required
the shared verdict. A single policy boundary keeps file pins, conversation
identity, execution evidence, routing strategy, and downstream visibility
consistent.

### Definitive quota provenance is emitted only for ownership-constrained selection

The load-balancer request records whether `required_account_id` represents an
ownership/continuity constraint. Only that class may return
`hard_affinity_owner_usage_exhausted=true` from definitive usage evidence.
Ordinary configured required-account routing continues through its existing
non-continuity failure/degraded-mode path.

This explicit bit is preferred over inferring intent from the presence of
`required_account_id`: the same field is used for both continuity and operator
routing, and conflating them would fabricate relocation authority.

### HTTP-bridge relocation converts only the current request into a fresh replay

When a pre-visible definitive owner quota receives a movable verdict, the bridge:

1. removes the exhausted upstream turn-state from the session,
2. excludes the exhausted account,
3. marks the current request's affinity reallocatable,
4. clears the request's hard-continuity-anchor flag because the replacement body
   is now account-neutral,
5. reconnects using that request-local relocation affinity, and
6. clears the reusable session's reallocation flag after selection.

The alternative — leaving the old hard anchor or reusable-session reallocation
authority in place — either selects the exhausted owner again or weakens later
ordinary reconnects.

### Durable operation identity is preserved but re-fenced on the replacement

If the bridge request already has a durable operation id and fingerprint, quota
relocation sets `operation_rebind_required`. The retry keeps the same dedupe
identity but the send boundary must bind that operation to the replacement owner
before dispatch.

Creating a new operation id would lose exactly-once lineage; reusing the old fence
without rebinding would incorrectly leave the operation owned by the exhausted
account.

### Execution evidence remains a hard fail-closed boundary

A quota event carrying a response id or other observed upstream execution does
not cross accounts merely because the error code is definitive. The shared
relocation policy continues to reject such movement as
`upstream_execution_observed`. This intentionally distinguishes pre-execution
quota rejection from an already-created response lifecycle.

## Risks / Trade-offs

- **A stale local replay proof could move the wrong body.** → Revalidate the
  ownership/body inputs at the relocation boundary and keep explicit
  turn-state/file/conversation gates fail-closed.
- **A durable operation could execute twice during bridge relocation.** → Preserve
  its id/fingerprint and require replacement-owner re-fencing before retry send.
- **Request-local sticky reallocation could leak into later turns.** → Pass it
  only into the relocation reconnect and clear the reusable session flag
  immediately after selection.
- **Generic required-account routing could be mistaken for continuity.** → Carry
  an explicit ownership-constraint bit and keep a regression for configured
  single-account degraded-mode behavior.
- **A definitive-looking error after upstream execution could be replayed.** →
  Keep response-id/event evidence as a shared-policy refusal regardless of quota
  code.

## Migration Plan

There is no schema or data migration.

1. Deploy the code and OpenSpec artifacts to Beta.
2. Validate direct HTTP, WebSocket, and HTTP-bridge definitive-quota paths plus
   generic/non-continuity routing regressions.
3. Exercise the product-level owner quota → replacement full resend → subsequent
   anchored continuation scenario.
4. Promote the same commit as the stable candidate only after Beta runtime
   validation. Rollback is a code rollback; no persisted schema conversion is
   required.
