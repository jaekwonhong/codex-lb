# Isolated artifact build qualification — 2026-09-18

The source-verified backend and Companion have now been built and tested as
isolated artifacts. This is build/OFF smoke qualification, not matched-pair
dispatch admission or production release qualification.

Evidence and both archives are in the operations workspace at
`artifacts/rotation-build-candidate-20260918/manifest.json`.

## Companion

- Version: `2.11.48-canary.1`, self-contained macOS arm64 Release publish.
- Executable SHA-256:
  `1ec90e2b7315a9a19d718b03ff7c8ec54e90ff72aa9ca92b83a060fe0456b2d1`.
- Two independent source directories produce identical executable and catalog
  bytes with `ContinuousIntegrationBuild=true` and `PathMap=<source-root>=/_/companion`.
  Without path mapping the assemblies differed; the mapped builds are the sealed
  artifacts. Source paths are therefore part of the documented build recipe.
- Ad-hoc signature verification passed. This does not assert notarization or a
  Developer ID signature.
- Release tests: 573 passed, 23 existing skipped. A published executable started
  with a temporary `LAUNCHER_DATA_ROOT`, `LAUNCHER_NO_OPEN=1`, member switching OFF,
  and an ephemeral port; its health endpoint returned 200. The process was stopped.
- The production Companion binary, profile data and port 53418 were untouched.

## Backend

- Immutable local image identity:
  `sha256:d36db8ef85e390575b9a18771af91ea72f61ce853f3de82985705812b754d617`.
- Image tag: `codex-lb:rotation-build-candidate-20260918`.
- Source snapshot: baseline `4acf0d9fffd99b5c8677dbed5df460c5ef04f7bd` plus
  previously verified uncommitted changes; 6,038 frozen source files are hashed.
  Labels explicitly mark the dirty source and bind its file-manifest SHA-256.
- A full Docker build stalled while resolving the external Dockerfile frontend.
  The completed build instead reuses exact historical qualified base image
  `sha256:c4d23d6b4e11e2b766262c6ae5d7180776673a25685a78fed26a2f8bc5416eed`.
  All 801 baseline runtime source files were checked against that image, and
  dependency locks, frontend, native build inputs and entrypoint were unchanged.
  Only 13 changed/new backend runtime files are overlaid. This is explicitly
  recorded as a qualified-base overlay, not a rebuild of every dependency.
- All 896 resulting app/script/config/static file hashes match the expected
  combination; unchanged frontend assets remain intact.
- An isolated read-only-root container, no external network, no published ports,
  no production mounts, temporary empty SQLite data and `restart=no` returned
  readiness 200. OFF scheduler execution performed no work. The container was
  stopped. This is not a shared-PostgreSQL compatibility or rollback check.
- Real Ed25519 verification ran inside the image using ephemeral synthetic keys.
  The new Companion tuple was deliberately rejected because release admission
  still names historical 2.11.47. No trust root or plan was installed.

## Production baseline drift and next gate

Read-only runtime inspection found Stable at `e9a66c0318c3` and Beta at
`c419e47d81c1`, both newer than this task's historical Q2 backend image. Their full
identities and labels are saved in `observed-live-baseline.json`. This packet must
not replace those newer runtimes.

Before release: re-evaluate the rotation delta against the current qualified
baseline under `docs/UPSTREAM_RELEASE_DEPLOYMENT_POLICY.md`, preserve subsequent
fixes, then build and qualify the resulting candidate. The new Companion digest
requires an explicitly reviewed provenance contract/registration; the old P4
owning commit and hash cannot be relabeled as this uncommitted candidate. Current
shared-data migration/recreation/rollback qualification, signer provisioning,
candidate-specific first-start gate and OFF deployment also remain open.
No production deployment, activation or live canary occurred in this step.
