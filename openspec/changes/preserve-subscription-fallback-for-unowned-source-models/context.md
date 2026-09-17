# Source-scoped subscription fallback — context

## Historical defect lineage

The local DGX donor packet introduced `source_scoped_model_requires_source()` in
historical commit `5f04ac4b05126d08508fa9d28808c237d114b692`. Its original implementation
used subscription-registry absence as the source-only signal. That helper was
latent in the donor packet: the two Responses HTTP 503 call sites were added
later by integration commit `1d97ded263e54107f893459c54032a53ec18f3ed`.
Together those two steps produced the Astra false positive when the persisted
model registry was cleared while the gateway API key remained scoped to the
DGX source.

Production correction commit
`4944cf1c5f830041f7a72ed6a4322633ef6ef5b3` changed the boundary to positive
model declaration by an assigned source and preserved the structural and
continuity subscription exceptions.

## Corrected packet reconstruction

For packet-level provenance, the historical donor root was reconstructed with
the ownership correction immediately after `5f04ac4b`:

- correction commit: `20d9340d9f3fda950385a6808e8af6aad8e37d6a`
- corrected packet branch: `codex/beta9-patch-packet-astra-corrected-20260917`
- corrected packet tip after replaying the original seven donor successors:
  `d478082855fa42cdcb9dc00f97631f880f4370a3`

The replay was conflict-free after the correction. Relative to historical
packet tip `30e67542f2dc83ca9f92ff8b729e2b825e17e0d8`, the corrected packet changes
only `model_sources/repository.py`, `model_sources/selection.py`, and focused
source-scope tests.

These SHAs are provenance, not the durable compatibility contract. Future
upstream rebases will naturally generate different commit IDs.

## Canonical reuse rule

The durable authority is `scripts/verify_beta_patch_packet.py`, contract
`beta_patch_packet_source_scope_v2`. Every future integrated Beta candidate that
carries the local DGX/source-scoping packet must pass that verifier after the
packet and its Responses integration have both been ported.

The canonical executable entrypoint is `scripts/qualify_beta_patch_packet.sh`; the existing `scripts/qualify_usage_member_rotation.sh` invokes it before Q2-specific checks. This turns the semantic contract from an operator memory item into a mandatory qualification dependency for the current production path.

The verifier intentionally checks the cross-commit semantic boundary rather
than commit ancestry:

1. source-only classification is async and proves model ownership against the
   sources explicitly assigned to the presented API key;
2. a dangling source scope with no remaining assignments still fails closed;
3. every Responses HTTP source-only guard awaits that ownership-aware helper;
4. structural source-route exclusions and continuity-suppressed subscription
   ownership bypass the final source-only guard.

A rebase must not qualify by merely cherry-picking historical donor SHAs. If the
helper or its call sites are reimplemented because upstream moved the code, the
new implementation still has to satisfy this semantic verifier and the route
regressions in this change.
