# Production Beta validation — 2026-10-07

## Qualified source

- Branch: `fix/production-beta-astra-local-history-auto-recovery-20261007`
- Runtime source head: `e9cca2448ea1efaac5573071dbbd40c0bc3bef2a`
- Functional Astra relocation completion: `e4ed13fad72f2f30424286e5c86453e98ddfe213`
- GLM compaction policy retained from `d7be9d0c1b0e9f2b21da247f2e57682b8c6a93e3`

`e9cca2448` only restores final validation formatting/gates around the already
qualified relocation paths; its affected owner-interruption regressions were
rerun before the exact-head deployment.

## Pre-deployment regression

The focused current-head suite passed 24/24, covering:

- HTTP-bridge owner `usage_limit_reached` -> account-neutral full-resend
  relocation -> replacement-owner continuation and durable-operation re-fence;
- advisory owner pressure refusal and explicit-anchor/no-history fail-closed
  behavior;
- direct-stream selection-time definitive owner quota using the shared
  relocation verdict;
- inline-image execution-evidence refusal;
- GLM compaction `low` / `32768` policy, source/operator ceilings, API-key
  reasoning policy, and incomplete-terminal preservation.

After the final `e9cca2448` head appeared, the four owner-interruption tests
touched by that commit were rerun and passed 7/7 (parametrized cases included).

## Immutable Beta image

The first full-source Docker build was rejected because Docker's Rust build stage
segfaulted while compiling the unchanged native-egress worker. The production
candidate therefore used the existing qualified Beta image as the immutable
runtime/native-egress base and replaced the complete `app`, `config`, and
`scripts` trees from the committed source, while rebuilding frontend static
assets with the repository's normal Bun stage. This matches the existing Beta
overlay operating model and does not alter the native-egress binary or Python
environment.

Final image:

- tag: `codex-lb-beta:astra-continuity-e9cca2448-20261007`
- digest: `sha256:4c7663f1cc0d8cc75473477a0aa335ad967a76cd0cd7000fefd1d484f5cb2e18`
- `org.opencontainers.image.revision=e9cca2448`
- `codex-lb.patch.astra-continuity-final=e4ed13fad`
- `codex-lb.patch.astra-local-history-auto-recovery=e9cca2448`
- `codex-lb.patch.glm-compaction-low=d7be9d0c1`
- `codex-lb.patch.compaction-profile=low-32768`

The deployed container's non-static `app/config/scripts` content was compared
against a detached `e9cca2448` worktree: 813 files, with no missing files, no
extra files, and no content-hash mismatch. Frontend `app/static` contains the
expected generated build artifacts and is therefore validated through the build
stage rather than source-file identity.

## Cutover and rollback

Cutover was allowed only after the existing 2456 connection byte counters were
quiescent. The existing container was stopped and renamed instead of deleted.
The new container reused the exact environment, mount set, loopback port binding,
read-only root filesystem, tmpfs, restart policy, PostgreSQL socket volume, and
runtime data volume.

Primary rollback retained:

- container: `codex-lb-beta-rollback-pre-astra-0f9f9fdba-20261007`
- image: `codex-lb-beta:glm-compaction-low-d7be9d0c1-20261007`
- digest: `sha256:eb0f97dfad921b5e21f8b926f6162a476b1cfac64048d21ca2265c71b4a742c6`

Deployment inspect snapshots are stored owner-only under the local
`codex-lb-gateway/deploy-backups` Astra-continuity qualification directories.

## Runtime health

The exact-head candidate reached `/health/ready` with database status `ok`.
After the stopped predecessor aged out of the bridge ring, repeated readiness
checks converged to and remained at:

- `bridge_ring.ring_size=2`
- `bridge_ring.is_member=true`
- no bridge-ring error.

Recent post-cutover logs contained no `hard_affinity_saturated`, `No available
accounts`, `owner_quota_relocation_declined`, `previous_response_owner_unavailable`,
or quota-relocation error. Stable was not changed.

## Real PC1 Astra smoke

PC1 was already on the Beta `codex-lb` profile. A fresh Codex CLI request using
`gpt-6-astra` returned the exact expected marker successfully. The same Codex
session was then resumed with `gpt-6-astra` and returned the continuation marker
successfully.

Server-side logs showed the first turn creating a hard thread-header bridge on
one selected Astra account and the second turn reusing that same bridge/account,
which validates the normal hard-continuity path on the deployed image.

Production quota exhaustion was **not** manufactured by changing account state
or consuming a live account purely for validation. The definitive quota
relocation behavior is instead covered by the focused end-to-end bridge/direct
stream regression suite above. A naturally occurring future owner-quota event
can therefore exercise the deployed recovery path without destructive canary
mutation.

## Decision

PC1 Beta is qualified on `e9cca2448` for the structural Astra owner-quota
auto-recovery change. The previous qualified Beta image remains available for
immediate code rollback, and Stable remains untouched. The long-running fork
`main` and this production branch have substantial parallel history, so this
validation does not authorize a blind full-history merge into `fork/main`;
integration should be done as a separately reviewed patch-port if/when the
server baseline is consolidated.
