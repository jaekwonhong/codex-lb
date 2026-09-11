## Implementation

- [x] Replace the lifecycle-driven member-switch runtime with explicit actions.
- [x] Preserve ambiguous state and guard identity, preview expiry and duplicate submissions.
- [x] Add visible loading, route failure and not-found states.
- [x] Build the entire frontend from source without minified bundle rewriting.

## Verification

- [x] Run type checking, lint and the frontend suite with outbound networking denied.
- [x] Test the manual UI using mocked API responses, including failure boundaries.
- [x] Inspect built core pages and before/after screenshots with every API intercepted.
- [x] Record patch identity, commands, results, limitations and next implementation gates.

Live account switching, OAuth, probes and production deployment are prohibited.
