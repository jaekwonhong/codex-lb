# Usage-driven Business member rotation P7 qualification

P7 is a non-destructive qualification and release-tooling layer over the G1 public boundary. It does not add a
rotation scheduler/controller, membership mutation client, OAuth flow, Companion installer, or deployment path.
The final G2 integration supplies small adapters that expose P5 effect counters and read reconciliation to this
harness.

## Frozen inputs

- G1 source parent: `ce807515439a285147c807f2a83b1f221cb67626`
- P4 artifact-owning ops commit: `47ac829a23b9811537bcd2d21ae9b8003c9c464a`
- P4 reconstructed-source baseline recorded by the artifact: `97becd4b66a5569efd3895d10ff7c9beec3eea97`
- P4 candidate: `2.11.47`
- P4 binary SHA-256: `0f7b665e47f1b2cd4959814afe3ee68fe0aa5cc25a264e295997d3499290f1ce`
- P4 patch gzip SHA-256: `eb8cb39de01e2b92c834f16bab571e8e3c1420d507113a146dd47da674e9f9fc`
- P4 decompressed patch SHA-256: `b4a4dca639f63870bd6800835905b8c5a68a5c54dc83d3a4d410e651bc7a48da`
- P4 isolated replay digest over the 14 touched files:
  `1feb8130c6d683569d8dd5d6f4e0a3a5f705afa6e66b53dc2e9e26eb614ed76d`

The P4 ops commit and reconstructed-source baseline are deliberately separate. The first owns the final P4
artifact; the second is the frozen ops state from which the exact live Companion source was reconstructed.

## Fixed qualification matrix

`tests/fixtures/member_switch/p7_qualification_matrix.json` is the machine-readable G2 contract. The source suite
uses the actual G1 Weekly/reset/quota/history/member-switch implementations for all boundaries available at G1.
The matrix reserves P5-specific scheduler/concurrency cases for a G2 adapter rather than importing P5 private
implementation into P7.

`scripts/qualify_usage_member_rotation.sh` runs the fixed source suite, Ruff, ty, and strict OpenSpec validation.
Pass `--with-p4` only when the frozen P4 files are available and set `P4_ARTIFACT`, `P4_MANIFEST`,
`P4_OPS_WORKTREE`, `P4_BASE_SOURCE`, and `P4_SCRATCH_ROOT`. The replay copies only P4-touched source files into an
auto-cleaned scratch directory, applies the gzip patch there, and verifies the frozen replay digest. It never
changes the live Companion source or installation.

## G2 no-replay adapter

The G2 controller adapter implements `RestartNoReplayAdapter` from
`scripts/member_rotation_release_qualification.py`. For reset consume, remove, and invite the harness performs the
same sequence: observe counters, cross exactly one effect boundary with a deliberately lost response, require a
durable operation/effect receipt, reconstruct the adapter from durable state, perform authoritative read-only
reconciliation of that exact receipt, and prove the external effect count did not increase. The P7 tests include
both replay-unsafe and wrong-receipt negative controls; the harness must reject them.

The final adapter must bind counters to the actual effect-bearing call sites. A synthetic controller state or a
mocked success flag is insufficient evidence. `durable_effect_receipt()` must read the committed receipt identified
by the real operation/effect, and `reconcile_read_only()` must return that same receipt from the authoritative
reconciliation read path. The restart instance must reuse the same durable database state while using a newly
constructed service/controller object.

## Deployment preflight evidence

The existing release/deployment tooling remains responsible for building and inspecting the candidate. P7 consumes
its read-only evidence with:

```text
python -m scripts.member_rotation_release_qualification preflight \
  --evidence <preflight.json> \
  --source-root <exact-g2-source-worktree> \
  --expected-source-sha <g2-sha> \
  --expected-package-version <package-version> \
  --expected-image-sha256 <immutable-image-sha256> \
  --expected-workspace-account-id <target-workspace-account-id> \
  --expected-stable-sha256 <stable-image-sha256> \
  --expected-beta-sha256 <beta-image-sha256> \
  --expected-postgres-container-id <postgres-container-id> \
  --expected-postgres-system-identifier <postgres-system-id> \
  --expected-rollback-stable-sha256 <beta.7-stable-image-sha256> \
  --expected-rollback-beta-sha256 <q2-beta-image-sha256> \
  --expected-rollback-stable-source-sha <beta.7-stable-source-sha> \
  --expected-rollback-beta-source-sha <q2-beta-source-sha> \
  --expected-rollback-stable-role <beta.7-stable-role> \
  --expected-rollback-beta-role <q2-beta-role>
```

The JSON evidence has these required sections:

```json
{
  "schema_version": 1,
  "subject": {"workspace_account_id": "<target-workspace-account-id>"},
  "candidate": {
    "source_sha": "<40-hex>",
    "package_version": "<version>",
    "image_sha256": "<64-hex>",
    "provenance_verified": true
  },
  "p4": {
    "version": "2.11.47",
    "binary_sha256": "<frozen P4 binary SHA>",
    "patch_sha256": "<frozen P4 patch SHA>",
    "patch_uncompressed_sha256": "<frozen P4 decompressed patch SHA>",
    "artifact_owning_ops_commit": "47ac829a23b9811537bcd2d21ae9b8003c9c464a",
    "reconstructed_source_baseline": "97becd4b66a5569efd3895d10ff7c9beec3eea97",
    "capability_verified": true,
    "provenance_verified": true,
    "contract": [
      "typed_remove_response_observation",
      "typed_invite_response_observation",
      "recursive_bounded_sanitization",
      "effect_boundary_no_replay"
    ]
  },
  "postgres": {
    "gate": "PASS",
    "container_id": "<64-hex docker container id>",
    "container_started_at": "<docker StartedAt>",
    "system_identifier": "<postgres cluster system id>",
    "current_revision": "20260913_000000_add_oidc_provider_flow",
    "official_head_revision": "20260913_000000_add_oidc_provider_flow",
    "member_rotation_extension_contract": "member_rotation_local_extension_v1",
    "member_rotation_extension_gate": "PASS",
    "extension_schema_sha256": "<64-hex canonical extension schema digest>",
    "snapshot_fingerprint": "<64-hex trusted DB snapshot fingerprint>"
  },
  "migration": {
    "policy": "PASS",
    "schema_drift": "PASS",
    "database_container_id": "<same postgres container>",
    "database_container_started_at": "<same StartedAt>",
    "system_identifier": "<same cluster id>",
    "current_revision": "20260913_000000_add_oidc_provider_flow",
    "head_revision": "20260913_000000_add_oidc_provider_flow",
    "candidate_head_revision": "20260913_000000_add_oidc_provider_flow",
    "extension_schema_sha256": "<same extension schema digest>",
    "postgres_snapshot_fingerprint": "<same trusted snapshot fingerprint>"
  },
  "operations": {
    "active_member_switch_controls": 0,
    "active_oauth_member_operations": 0,
    "oauth_device_slots": 0,
    "automatic_rotation_enabled_rows": 0,
    "postgres_snapshot_fingerprint": "<same trusted snapshot fingerprint>"
  },
  "runtime": {
    "stable_before_sha256": "<64-hex immutable digest>",
    "stable_after_sha256": "<same digest>",
    "beta_before_sha256": "<64-hex immutable digest>",
    "beta_after_sha256": "<same digest>",
    "postgres_snapshot_fingerprint": "<same trusted snapshot fingerprint>"
  },
  "feature": {
    "default_enabled": false,
    "enabled": false,
    "configuration_effects": {
      "reset_consume": 0,
      "remove": 0,
      "invite": 0,
      "join": 0,
      "oauth": 0
    },
    "automatic_effects_during_off_window": {
      "reset_consume": 0,
      "remove": 0,
      "invite": 0,
      "join": 0,
      "oauth": 0
    },
    "postgres_snapshot_fingerprint": "<same trusted snapshot fingerprint>"
  },
  "rollback": {
    "exists": true,
    "identity_sha256": "<64-hex verified pg_basebackup manifest digest>",
    "verified": true,
    "strategy": "restore_pre_migration_database",
    "artifact_kind": "postgresql_physical_base_backup",
    "backup_contract": "postgresql_catalog_preserving_physical_v1",
    "backup_manifest_sha256": "<same verified pg_basebackup manifest digest>",
    "backup_manifest_verified": true,
    "post_migration_predecessor_boundary": {
      "stable": {
        "probe_kind": "migration_state",
        "compatible": false,
        "image_sha256": "<exact beta.7 Stable image>",
        "source_sha": "<exact beta.7 Stable source>",
        "role": "<exact beta.7 Stable role>",
        "database_container_id": "<admitted beta.9 DB container>",
        "database_container_started_at": "<same admitted beta.9 DB StartedAt>",
        "system_identifier": "<same admitted beta.9 DB cluster id>",
        "current_revision": "20260913_000000_add_oidc_provider_flow",
        "head_revision": "20260910_000000_request_logs_missing_cost_index",
        "needs_upgrade": true,
        "is_ahead": true,
        "unknown_revisions": ["20260913_000000_add_oidc_provider_flow"],
        "extension_schema_sha256": "<same admitted beta.9 extension schema digest>",
        "postgres_snapshot_fingerprint": "<same admitted beta.9 snapshot fingerprint>"
      },
      "beta": "<same boundary proof for exact Q2 Beta predecessor>"
    },
    "source_database": {
      "system_identifier": "<pre-migration PostgreSQL system identifier>",
      "current_revision": "20260910_000000_request_logs_missing_cost_index",
      "head_revision": "20260910_000000_request_logs_missing_cost_index",
      "member_rotation_extension_preserved": true,
      "extension_schema_sha256": "<six-table local-extension schema digest>",
      "extension_tables": {
        "member_switch_control_records": {"count": 0, "sha256": "<64-hex data digest>"},
        "member_switch_command_receipts": {"count": 0, "sha256": "<64-hex data digest>"},
        "member_rotation_quota_operations": {"count": 0, "sha256": "<64-hex data digest>"},
        "member_rotation_workspace_controls": {"count": 0, "sha256": "<64-hex data digest>"},
        "workspace_member_usage_reset_invalidations": {"count": 0, "sha256": "<64-hex data digest>"},
        "workspace_member_final_usage_snapshots": {"count": 0, "sha256": "<64-hex data digest>"}
      },
      "snapshot_fingerprint": "<verified pre-migration rollback snapshot fingerprint>",
      "backup_identity_sha256": "<same verified backup digest>",
      "legacy_credential_columns": [
        "password_hash",
        "totp_secret_encrypted",
        "totp_last_verified_step"
      ],
      "legacy_credential_fingerprint_sha256": "<hash-only credential-state fingerprint>",
      "retired_sentinel_present": false
    },
    "restore_rehearsal": {
      "database_container_id": "<isolated restored DB container id>",
      "database_container_started_at": "<restored DB StartedAt>",
      "system_identifier": "<restored DB cluster id>",
      "current_revision": "20260910_000000_request_logs_missing_cost_index",
      "head_revision": "20260910_000000_request_logs_missing_cost_index",
      "member_rotation_extension_preserved": true,
      "extension_schema_sha256": "<same six-table local-extension schema digest>",
      "extension_tables": "<same six per-table count + data-digest mapping as source_database>",
      "snapshot_fingerprint": "<same verified pre-migration rollback snapshot fingerprint>",
      "source_snapshot_fingerprint": "<same verified pre-migration rollback snapshot fingerprint>",
      "backup_identity_sha256": "<same verified backup digest>",
      "legacy_credential_columns": [
        "password_hash",
        "totp_secret_encrypted",
        "totp_last_verified_step"
      ],
      "legacy_credential_fingerprint_sha256": "<same hash-only credential-state fingerprint>",
      "retired_sentinel_present": false,
      "catalog_representation_preserved": true
    },
    "predecessor": "<exact beta.7 Stable/Q2-Beta image + source + role identities>",
    "stable_start_probe": {
      "probe_kind": "runtime_start",
      "compatible": true,
      "image_sha256": "<exact beta.7 Stable image>",
      "source_sha": "<exact beta.7 Stable source>",
      "role": "<exact beta.7 Stable role>",
      "container_id": "<started predecessor container id>",
      "container_started_at": "<predecessor StartedAt>",
      "running": true,
      "ready": true,
      "readiness_path": "/health/ready",
      "readiness_status": 200,
      "restart_count": 0,
      "migrate_on_startup": false,
      "database_container_id": "<restored DB container id>",
      "database_container_started_at": "<restored DB StartedAt>",
      "system_identifier": "<restored DB cluster id>",
      "current_revision": "20260910_000000_request_logs_missing_cost_index",
      "head_revision": "20260910_000000_request_logs_missing_cost_index",
      "needs_upgrade": false,
      "is_ahead": false,
      "unknown_revisions": [],
      "extension_schema_sha256": "<same restored six-table extension schema digest>",
      "postgres_snapshot_fingerprint": "<same restored pre-migration snapshot fingerprint>"
    },
    "beta_start_probe": "<same runtime-start/readiness proof for exact Q2 Beta predecessor>"
  }
}
```

The final ops preflight must use the host-side local-extension gate to validate the six Beta-local tables (two retained
member-switch tables plus four rotation tables) without moving the official Alembic head. Migration, operation,
feature-OFF, and matched beta.9 runtime evidence bind to one admitted post-migration beta.9 snapshot. The same epoch
must include read-only migration-state probes from the exact beta.7 Stable and Q2-Beta predecessor builds showing the
database is ahead/unknown and therefore incompatible; that positive boundary evidence prevents a later rehearsal from
silently treating the non-rolling migration as rolling-safe. Rollback is a separate database epoch: P7 binds a verified
catalog-preserving physical PostgreSQL backup at `20260910...` directly to the sealed source snapshot, records its
verified backup manifest digest plus count + data SHA-256 for each of the six local extension tables, and proves an
isolated physical restore preserves the source PostgreSQL system identifier, exact local-extension catalog/schema
fingerprint, per-table fingerprints, and legacy dashboard credential state. A logical `pg_dump`/`pg_restore` rehearsal
may still be used for beta.7→beta.9 migration testing, but it is not an operational rollback artifact for the immutable
Q2 predecessor because PostgreSQL may rewrite `pg_get_constraintdef()` representation. Only then are exact predecessor
runtime-start probes accepted. Those probes must
prove the expected image/source/role has a container `StartedAt` strictly later than the restored database `StartedAt`,
stayed running with zero restarts, reached `/health/ready` with HTTP 200, had startup migrations disabled, and remained
bound to the restored predecessor-head snapshot.

The original G2 source placed the four rotation tables in two local Alembic revisions. Q2 release review proved that
this conflicts with the shared PostgreSQL contract because pristine Stable must keep the official upstream head. The
Q2 closure therefore removes those unshipped local revisions, keeps the ORM models, treats the four rotation tables as
Beta-local extensions alongside the two retained member-switch extension tables, and requires an independent
fail-closed runtime/ops extension contract. A rollback restores the verified pre-migration database artifact; it does
not depend on an in-place beta.9 Alembic downgrade.

During the beta.9 integration, separate read-only backend/shared and frontend/OpenSpec reviews were rerun against the
exact-current Q2 semantic rebase. Both returned no blocking findings after the beta.9 permission, Alembic-head,
read-only-query, and rollback-contract corrections. These reviews do not authorize live effects; the source/test and
rehearsal gates remain independently required.

## Rollback qualification

Capture normalized count + SHA-256 fingerprints from the sealed pre-migration source and the restored rollback database for `quota_history`,
`unknown_effect_receipts`, `removed_member_snapshots`, `reset_resolution_state`, and `oauth_member_records`. Then
run:

```text
python -m scripts.member_rotation_release_qualification rollback \
  --before <before.json> \
  --after <after.json> \
  --expected-rollback-stable-sha256 <beta.7-stable-image-sha256> \
  --expected-rollback-beta-sha256 <q2-beta-image-sha256> \
  --expected-rollback-stable-source-sha <beta.7-stable-source-sha> \
  --expected-rollback-beta-source-sha <q2-beta-source-sha> \
  --expected-rollback-stable-role <beta.7-stable-role> \
  --expected-rollback-beta-role <q2-beta-role>
```

Every durable category and all six local-extension table fingerprints must match exactly between the sealed
pre-migration source snapshot and the restored rollback database. The restore must return to
`20260910_000000_request_logs_missing_cost_index`, restore the three legacy dashboard credential columns/value
fingerprint, keep `dashboard_legacy_credentials_retired` absent, preserve the pre-migration PostgreSQL system identifier
and catalog representation, and bind both the source and restored snapshot to the exact verified physical backup manifest
digest. Only the restored database is used for exact beta.7 Stable/Q2-Beta predecessor start
probes; each must bind the expected image/source/role, have a container `StartedAt` strictly later than the restored DB
epoch, actually start and become ready with migrations disabled and zero restarts, report current/head at
`20260910...`, `needs_upgrade=false`, `is_ahead=false`, no unknown revisions, and retain the restored snapshot/extension
fingerprints. The separate post-migration boundary probes must show those same predecessor builds reject the admitted
`20260913...` beta.9 snapshot as ahead/unknown. This keeps unresolved remove/invite evidence durable without pretending
beta.7 is compatible with the beta.9 schema.

For the beta.9 Q2 candidate, the historical `.q2-beta-start-gate-592ace38-v1` sentinel is not reusable. The first-start
gate must be admitted with the final immutable image digest plus exact source/tree SHAs, verify those provenance labels
from the immutable image config as well as the effective container config, verify the original entrypoint bytes, and run
with exact `restart=no` while gated. Its sentinel uses the new full-image-derived beta.9 namespace and is published with
an atomic no-overwrite protocol. Release is accepted only when the same PID1 starttime and network namespace exec the
app; an outcome-unknown publish remains fail-closed. Post-stop sentinel revocation additionally requires the exact
candidate to be stopped and the revocation view to share the same runtime mount.

## Final live-canary guard

P7 does not run the live canary. Trace validation and mutation authorization are deliberately separate. Validation
alone never grants permission to mutate:

```text
python -m scripts.member_rotation_release_qualification canary \
  --events <recorded-trace-prefix.json> \
  --next-effect none
```

Immediately before the eventual remove or invite, G2 must submit the already-recorded trace prefix and explicitly
request authorization for exactly that next effect:

```text
python -m scripts.member_rotation_release_qualification canary \
  --events <recorded-trace-prefix.json> \
  --next-effect remove
```

or `--next-effect invite`. A sent effect must then be durably appended to the trace before any capture/reconciliation
step. The authorizer rejects a second remove or invite once its budget is consumed, so capture failure cannot become
retry permission. Invite authorization additionally requires authoritative reconciliation of the single remove.
`reset_recovered` forbids later replacement events. A remove-only or invite-only trace may stop only after its
authoritative reconciliation, while `mark_success` requires authoritative `join_confirmed`. `threshold_probe` and
`discovery_churn` are rejected.

Automatic rotation remains default OFF. A deployment with the feature disabled and a configuration change are both
qualified only when all external-effect counters remain zero. Enabling automatic rotation is outside P7 and occurs
only after G2 qualification and the separately authorized live canary.
