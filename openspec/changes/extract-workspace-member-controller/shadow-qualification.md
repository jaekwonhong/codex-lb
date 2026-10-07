# Read-only shadow qualification — 2026-10-06

## Scope

This qualification covers only the standalone Workspace Member Controller read plane. It does not authorize or expose membership mutation, account-pool routing, reset-credit mutation, or production ownership transfer.

The qualified shadow ran as a separate service on the Mac host with these boundaries:

- host exposure: `127.0.0.1:2461` only;
- container root filesystem: read-only;
- Linux capabilities: all dropped;
- `no-new-privileges`: enabled;
- Controller `/v1` reads: dedicated bearer-admin protected;
- membership mutation HTTP route: absent (`404` in the live shadow);
- migration database: dedicated `workspace_member_controller_shadow` role with no superuser/role/database creation privileges and `default_transaction_read_only=on`;
- explicit member-to-OpenCodex binding file: valid and intentionally empty for this read-only qualification;
- OpenCodex readiness: required even with zero bindings;
- Companion: existing qualified installed binary used only as the read/observation source for the shadow comparison.

The existing Codex-LB Stable, Beta, and PostgreSQL containers were not restarted for the shadow qualification.

## Comparison method

The existing Codex-LB implementation and the standalone shadow were read against the same installed Companion and the same Controller-owned migration database state.

The comparison intentionally excluded volatile observation timestamps. Membership observations were normalized only by removing `observedAt` and sorting member entries; all identity, completeness, owner verification, ambiguity, catalog/workspace identity, code, and member-state fields remained part of the comparison.

No mutation command was sent as part of qualification.

## Results

| Check | Result |
| --- | --- |
| Catalog payload | exact semantic match |
| Workspace count | 3 on both paths |
| Active membership operation | exact match |
| Workspace intent/account/version state | exact match for all 3 workspaces |
| Membership observations | semantic exact match for all 3 after excluding `observedAt` |
| Existing error state | preserved exactly by shadow; not normalized away |
| Healthy observations | completeness and owner-verification state matched |
| Unauthenticated `/v1` read | rejected (`401`) |
| Authenticated `/v1` read | accepted (`200`) |
| Membership mutation HTTP attempt | no route (`404`) |
| Interactive docs/OpenAPI | unavailable (`404`) |
| Shadow restart/readiness | passed |
| Database write probe with shadow role | denied as expected |

One of the three existing workspace observations was already in a non-success owner-membership response state on the legacy path. The shadow reproduced the same code and observation semantics. The other two observations were complete and owner-verified on both paths. This is evidence of read-path equivalence, not evidence that the pre-existing observation error is resolved.

## Qualification conclusion

The standalone Controller read path is qualified for continued read-only shadow operation on this host. There were no legacy-vs-shadow read mismatches in catalog, active operation, workspace intent, or membership observation semantics for the three-workspace sample.

This qualification does **not** qualify account-dependent rotation because the shadow binding set is intentionally empty, and it does **not** qualify any membership effect. Those remain gated by the separately authorized single-workspace mutation canary.

## Follow-up exact-account projection qualification — 2026-10-07

A later read-only follow-up closed one gap in the original shadow evidence
without enabling mutation. The running shadow had accidentally mounted the
OpenCodex `service-api-token` at its `WMC_OPENCODEX_ADMIN_TOKEN_FILE` path. That
mistake was latent because the live shadow still had zero account bindings: its
readiness checked OpenCodex `/readyz` but had no exact account-state request to
authorize.

The OpenCodex Controller contract requires the raw management `admin-token`
principal by design. The shadow mount was corrected to the owner-only
`admin-api-token` file while preserving the same image, environment, loopback
port, read-only root filesystem, dropped capabilities, no-new-privileges policy,
database role, and all other mounts. The previous container was retained as a
stopped rollback container.

The retained two-binding canary snapshot was then supplied only to a one-shot
standalone `--validate` container. That validation used the same Companion,
Controller database, OpenCodex management endpoint, and corrected read-only
admin-token mount. It completed successfully with:

```text
workspace-member-controller validation passed: workspaces=3 bindings=2 opencodex_accounts=2
```

This proves the exact binding -> member/catalog identity -> OpenCodex
`controller-account-state` read path for two bound accounts. It still does not
authorize membership mutation, quota/reset-credit mutation, or account-routing
ownership transfer. The live shadow binding set remains intentionally empty.

## Retained live shadow state

At qualification close, the shadow service remains running for observation only. Its runtime is intentionally independent of Codex-LB Stable/Beta. Stopping or removing the shadow does not require restarting the existing inference services.
