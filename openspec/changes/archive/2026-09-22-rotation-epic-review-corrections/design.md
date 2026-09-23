# Design

## Scope
Correct the six source-bound review findings without changing the production
generation, database schema, durable effect budgets or Git lineage. The frozen
starting worktree already contains earlier uncommitted rotation work; the new
delta is measured against captured bytes, not inherited HEAD alone.

## Reset admission
The serialized central executor accepts an optional account-aware final guard.
It calls the guard after discovery and durable pinning, immediately before the
consume callable. The worker checks the actual credential identity, freshly
observed member, unchanged/unexpired plan and enabled intent; membership age,
Weekly exhaustion/freshness and runtime evidence are checked after awaited reads.
Guard exceptions retain their identity and cannot be translated into a no-credit
or recovered reset outcome. Cancellation follows existing claim cleanup. The
durable pin remains conservative no-replay evidence, including rejected attempts.

This is a local admission boundary, not a distributed lock over remote membership
or a promise to recall a request already sent. Ordinary callers without a guard
retain the existing centralized serialized behavior.

## Pre-start interruption
The single-evaluation worker requests explicit attention for an existing controller
that has no durable start claim. Generic controller resume compatibility remains
available to callers with separately supplied fresh evidence. The worker never
fabricates that evidence or resets the fixed binding. Snapshot/preview state and
quota are retained for an explicitly reviewed recovery procedure.

A start claim can become visible after a conservative parent attention write.
Only the specific pre-start-attention reason may enter existing reconciliation
when such a claim is observed; the path cannot issue a new start or reset.
Completed cleanup and other attention outcomes keep their existing behavior.

## Operator and tests
Intent updates return primitive values from the successful UPDATE RETURNING row,
captured before commit and returned only after commit succeeds. Session state is
synchronized so a same-session intent read is not left stale. Insert responses
are similarly captured from the flushed row and returned after commit.

The frontend adopts the existing canonical uppercase-H numeric aliases. No
global alias-generator override or multi-spelling fallback is added. Actual ASGI
response bytes go through the real TypeScript schema/client; component tests also
cover the human-readable pre-start attention blocker. The ambient scheduler seam
is complete while dedicated scheduler tests continue exercising the real loop.

## Qualification and release boundary
Qualification uses scratch SQLite, synthetic upstream/Companion transports and
network fences, plus frontend source copies and installed tooling. No new image,
PostgreSQL rehearsal, live canary or production observation is claimed. The last
admitted deployment remains b98/e55; corrected source is not deployed. Current
documentation points to the correct read-only observer and preserves dated seals.
