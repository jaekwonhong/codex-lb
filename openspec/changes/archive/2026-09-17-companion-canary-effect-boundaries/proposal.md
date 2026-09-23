## Why

The backend starts one Companion operation which internally deletes then invites.
The P7 trace checker cannot enforce a budget at these actual network boundaries.
The managed operation also drops the typed delete response after verification.

## What Changes

- Add an explicit default-false canary start flag on the existing trusted start
  contract. This flag selects bounded execution; it does not bypass any existing
  caller, preview, identity, quota, or release authorization requirements.
- Bind at most one canary client flow for the lifetime of the durable operation
  store. Releasing or restarting it never replenishes its effect budget.
- Persist distinct remove/invite claims before their browser calls; require
  authoritative outgoing absence before the invite claim.
- Preserve sanitized remove telemetry in operation state and the backend model.

## Impact

This is a source candidate only. The scheduler and runtime provenance provider
remain separate gates. No live canary, deployment, reset or membership effect is
part of this implementation. Existing untagged manual operations stay manual.
