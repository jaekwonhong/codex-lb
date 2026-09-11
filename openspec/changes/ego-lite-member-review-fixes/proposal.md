# Ego Lite member failure-boundary repairs

## Why
Review of deployed 4570192 found lost unknown outcomes, delayed-close deadlock, close/reopen policy mismatch, and transient HTTP failures misclassified as logout.

## What Changes
Preserve session uncertainty; reconcile an exact recorded closed target by observation only; permit explicit preparation after known browser-open failure without reissuing OAuth; distinguish authentication from availability failures.

## Impact
Companion runtime, durable participant receipts, explicit reconciliation endpoint, backend action policy, frontend recovery guidance, and regression tests. No DB migration or live-account mutation. Existing owner AND recipient CDP membership/acceptance paths remain unchanged; full CDP removal is not claimed.
