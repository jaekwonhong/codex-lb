## Why

The controller currently accepts a caller-supplied P4 tuple without a current
host observation. The application has no server-owned rotation scheduler.

## What Changes

Add externally signed, short-lived host runtime evidence checked at dispatch.
Add a default-off lifecycle-managed scheduler restricted to one configured Q3
evaluation, using existing Weekly/reset/quota/controller paths. Automatic starts
use the bounded Companion endpoint. Keep the qualified release tuple unchanged.

## Impact

Source-only implementation and synthetic qualification. No signer keys, enabled
canary plan, runtime files, deployment, or live effects are installed by this work.
