## Context

The current selector has usage/headroom and in-flight accounting, while the bridge
has verified full-resend and recovery-attempt fences. These are reused. A new
retry engine, unconditional affinity deletion, arbitrary hidden-state deletion,
or forced usage-reset redemption would bypass established contracts.

## Decisions

1. Use fresh, applicable quota observations, not plan-name guesses. Distinguish a
   timestamp authorizing another admission attempt from a quota-window reset.
   Preserve model-specific quota and credit policies. Derived headroom affects
   selection, not persisted upstream-health diagnosis.
2. Use one small typed recovery policy, monotonic timing for control budgets and
   epoch time only for advertised reset horizons. The two-second same-owner wait
   limit is cumulative, not renewed at every nested retry. The five-second recovery
   budget does not include normal inference or completed-turn idle time.
3. Preserve ownership by default. Move a turn only on existing complete-context
   proof with an unaccepted operation, no file owner, no explicit client anchor,
   and a healthy authorized alternate. Reuse the existing request-local replay
   key/operation fence, rather than deleting shared ownership pre-emptively.
4. A successful transfer must establish coherent continuation on its replacement;
   rejected/failed preparation may not corrupt the previous mapping. Do not bounce
   back to the exhausted account during the same recovery attempt.
5. Do not force 2-second retry polling when upstream requires a longer wait. A
   long/unknown horizon triggers safe transfer if proven, otherwise a classified
   failure retaining the real retry hint. No synthetic success/response.created.
6. Use existing serialization and cancellation-safe lease release. Concurrent
   requests never share an AsyncSession. No global lock across network I/O.

## Non-goals

- No commercial quota circumvention or automatic paid-capacity activation.
- No automatic model/effort downgrade; no removal of account/file/auth isolation.
- No percentage improvement guarantee without measurements.
- No changes to generational midstream/replay uncertainty rules just to fit a UX
  timer; cancellation-safe settlement still completes before a turn is retried.
- No production rollout, push/merge or PC2 helper scripts in this implementation.

## Validation

Before/after tests must show: short known hold -> same-owner recovery; 31-second
hold -> no 31-second parking; expired default hold + fresh exhausted quota -> no
repeat submission to the exhausted account; verified full history -> transfer
before dispatch; missing history/file/client anchor/unknown acceptance -> no
transfer; nested retry -> shared budget; concurrent lease changes -> admission
revalidated; cancel -> no waiting tasks/leases left. HTTP bridge, raw HTTP and WS
must be tested where affected, including model-source and cross-provider replay
regressions. Record exceptions or incomplete coverage explicitly.
