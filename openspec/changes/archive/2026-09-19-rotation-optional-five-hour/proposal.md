## Why

5H availability varies by account and subscription response. Requiring every successful Weekly receipt to contain a 5H window rejects valid Weekly-only accounts.

## What Changes

Classify 5H as observed, not provided by this successful response, or unknown. Permit Weekly-only final retention only with explicit same-fetch absence evidence. Persist versioned provenance, validate immutable epoch recovery, and expose absence distinctly in operator UI/history. Do not infer availability from plan labels or old storage rows.

## Impact

Usage receipts, final retention/recovery, operator API and UI. No database migration, deployment, activation, live canary, real reset, or real membership effects.
