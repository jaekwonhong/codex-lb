# Optional five-hour Beta OFF release — 2026-09-20

Normative contract: [member-switch commands](spec.md). This page describes the
recorded deployment, not a fresh observation of the host.

The Beta-only replacement completed at **2026-09-20 11:34:14 KST**. Canonical Beta
container `564cf642b315f998d61b2e1351f7e650bedfe51b913ced296118b8d2a3d18317` used image
`sha256:b98fe0f7b9081c399c1c7728ba70e86b37624f2dd06edb934dfd15cc223b6d74`, source manifest
`e55b3132eaa349e93986226c543922555533348c363a304551f63faef0394a9b` and canonical content
digest `5a318a6e64fafd382ab6a7532c3f149d69b5f3bf94c14a2596a4e5bbe9ba02ce`.
Inherited Git HEAD alone is not its exact source identity. The image was a
verified base overlay with rebuilt frontend static assets, not a fresh native
dependency build.

Stable, PostgreSQL and Companion were preserved. The immediate rollback
predecessor is container `817ca6d00c723974a4c32c49128e576d77b53804ab1446d2405ae1a1aaf3c63b`
with image c409, retained stopped, restart=no and disconnected. The older
9520/6450 object is not the immediate predecessor. Rotation stayed OFF; the
release grants no enabled plan, reset, remove, invitation or canary authority.

## Evidence and read-only admission

The sealed release packet is:

`/Users/nowtech/Documents/codex-lb-server/artifacts/rotation-optional-five-hour-off-release-20260920T014016Z`

Its `production-deployment.json` records the transaction and `current-operations.md`
defines the release-specific operational boundary. The release manifest SHA-256
is `3e09dd0dc12087322340d17c1cb099894a120b4987745c394709ebca78c9f065`.

```sh
cd /Users/nowtech/Documents/codex-lb-server/artifacts/rotation-optional-five-hour-off-release-20260920T014016Z
PYTHONDONTWRITEBYTECODE=1 python3 -B current_operations.py check
```

This entrypoint supports **check only**. Do not run the historical c409
`current_ops.py recreate`, rerun the committed `deploy_beta_off.py execute`,
delete the journal/sentinel, or start the predecessor beside Beta. A failed
check calls for investigation, not relaxed pins or an automatic rollback.
Any new lifecycle/recovery operation needs a separately reviewed generation.

The follow-up archive/synchronization completed separately in
`rotation-optional-five-hour-off-release-openspec-followup-20260920T085447Z`, manifest
`db09eb11c5121151ead521900803765a2b986994b0bd4a63b96eea4b4f6f3aab`.
The original release packet's archive-pending statement remains historical;
the sealed packet was not rewritten.

## Subsequent source work is not deployed

The `rotation-epic-review-corrections` source work addresses review findings after
this release. Its tests/spec archive do not redeploy b98. Q3 remains **NOT RUN /
NOT ADMITTED**; explicit same-fetch 5H absence support does not itself authorize
rotation. A fresh admitted plan, operational need and all effect guards would
still be required. This page grants no commit/merge, backup deletion or live effect.
