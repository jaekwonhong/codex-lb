## Why

The rotation candidate was built from a historical Q2 baseline. Current Beta is
62cd34ce and contains subsequent routing/auth/usage fixes that must be retained.
The reproducible 2.11.48-canary.1 artifact has no owning Git commit and must not
borrow the historical 2.11.47 owning commit as its identity.

## What Changes

Apply only the verified rotation delta to the observed current Beta source.
Register the new Companion by its exact version, executable SHA-256 and canonical
source-manifest SHA-256, with no fabricated owning commit. Retain historical P4
qualification separately. Keep default OFF and all dispatch/capability guards.

## Impact

No Stable edit, production rollout, DB mutation, signer installation or canary
execution. Artifact registration is one prerequisite, not activation authority.
