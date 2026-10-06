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

## Retained live shadow state

At qualification close, the shadow service remains running for observation only. Its runtime is intentionally independent of Codex-LB Stable/Beta. Stopping or removing the shadow does not require restarting the existing inference services.
