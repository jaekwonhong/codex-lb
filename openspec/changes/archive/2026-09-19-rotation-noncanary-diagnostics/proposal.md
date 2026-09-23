## Why

The operator requested continued investigation without a live canary. The prior
preflight stops at missing same-fetch 5H data, leaving later conditions unobserved.

## What Changes

Add a diagnostic-only runner that compares numeric fields from one actual Usage
response with production parsing/classification and reports independent remaining
checks even when retention fails. Deny DB writes and Companion effect endpoints.
No production code, retention policy, deployment, intent or canary budget changes.

## Impact

Host diagnostic artifacts and OpenSpec context only. Real observations remain
point-in-time diagnostics and never confer activation authority.
