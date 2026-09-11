# Change: Keep owner preflight assistance recoverable

## Why
The migrated owner personal check can hand a logged-out or mismatched profile to the user. The failure cleanup immediately repeats personal preparation, reclaiming that same Space. The backend only permits explicit pre-membership closeout for the legacy personal_switch_not_confirmed code, so new known owner failures strand the managed run and show unavailable catalog recovery guidance.

## What Changes
Do not run owner cleanup after unsuccessful owner personal preparation. Allow explicit finish for known owner preflight failures only with complete, contiguous durable trace proving no membership mutation, no invitation state and no OAuth/browser participant. Keep uncertain/truncated/post-mutation cases retained. Tailor recovery text to actual allowed actions; do not tell active-run users to click disabled catalog controls.

## Scope
Owner preflight failure, existing backend finish policy and panel recovery text; no generic reset, additional automatic retry, real membership mutation, deployment, DGX change or data migration.
