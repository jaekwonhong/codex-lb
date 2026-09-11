# Simplify beta member switch

## Why

The deployed 1.24 packet1 frontend starts recovery, authentication, cleanup and
unbounded replacement retries from page lifecycle effects. Even preview can
mutate authentication. These paths obscure who authorized the next action.

## What Changes

- Replace the dashboard-wide automatic runtime with an Accounts-local,
  explicit manual workflow: catalog, preview, one start, status, authentication,
  finalization. Keep existing server and Companion contracts.
- Remove automatic rotation, automatic recovery, usage probing, candidate
  management and routing policy changes from this minimal panel.
- Retain uncertain/in-flight operation identity; never use lease expiry, a
  transport failure, or HTTP 404 as proof that a mutation did not happen.
- Show route loading, route failure and unknown-route states instead of blank
  content. Validate all core pages with synthetic responses only.

## Scope

Candidate source is the deployed image's tree
`0257caf579260fc370b19f20907ea392ab0ebb0f`, restored inside the requested workspace.
No running service, real account, credential, shared database or Companion is
changed. No live tests, deployment, merge, push or commits are included.
