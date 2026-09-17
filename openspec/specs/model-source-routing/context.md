# Model Source Routing — Context

## Purpose

Capability-based routing and accounting for OpenAI-compatible model sources,
including field-preserving embeddings forwarding.

This capability keeps source selection separate from subscription-account
routing: embeddings traffic is served only by sources that declare the
embeddings capability, while Responses/chat/audio continue to use their own
capability gates. Field presence (including explicit nulls) is preserved on
embeddings forwards so compatible sources see the same payload shape the
client sent.


## Local Beta patch-packet compatibility

The DGX/source-scoping overlay spans both model-source selection and the later
Responses HTTP integration, so commit ancestry alone is not a safe reuse
contract. Local Beta rebases must qualify the integrated source-scope boundary
with `python -m scripts.verify_beta_patch_packet`. The verifier treats positive
model declaration by an API key's assigned source as the source-only ownership
signal; a missing subscription-registry entry by itself is explicitly
non-authoritative. This prevents a registry-cleared deployment from classifying
a newer subscription model as belonging to an unrelated private source, while
retaining fail-closed behavior for actual source-owned models and dangling
source scopes.
