# Change: Repair managed member UX and uncertain runtime responses

## Why
Workspace-specific observation failures offer candidate selection without recovery guidance. Catalog requests remain possible before stored work is confirmed. Runtime parsing can convert missing uncertainty flags into a known result.

## What changes
Explain owner-space failures at the affected workspace; keep healthy workspaces usable but gate candidate selection and OAuth enrollment on authoritative membership observation. Require confirmed stored state before live catalog refresh. Reject incomplete or wrongly typed runtime result envelopes as unknown, preserving the first durable command and no-replay behavior.

## Scope
Managed member-switch frontend and the existing Ego runtime result parsers and consumers. No new mutation/recovery authority, production deployment, live membership effect, DGX or general login CDP change.
