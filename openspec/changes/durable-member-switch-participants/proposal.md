# Durable browser and session command receipts

Extend the isolated participant-contract candidate. Persist admission and exact
completion evidence for session preparation, browser opening and browser closing.
Recover a lost reply by reading the recorded command, never by replaying its effect.
Separate session preparation from OAuth preparation so reconciliation cannot
silently start OAuth. No operational rollout, upstream calls, or automatic worker.
