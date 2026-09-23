# P2 corrections

The original optional-5H packet and independent HOLD report remain historical evidence. Corrections are recorded separately under `artifacts/rotation-optional-five-hour-p2-fix-20260919T132704Z` in the operations workspace.

A complete legacy pair may contain opaque JSON such as `{"source":"live_upstream_fetch","fetch_id":"legacy-fetch"}`. Such an object must not be mistaken for v2 simply because it has no schema version. Explicit versioned evidence and recognizable incomplete v2 must still be rejected when invalid; legacy compatibility never authorizes a single Weekly row.

A retained 5H row may remain as raw history while its epoch validation is unknown. The UI must preserve that distinction, rather than labeling its usage/reset as validated evidence. No caller-selected evaluation/epoch trust boundary, quota or membership execution behavior is changed.
