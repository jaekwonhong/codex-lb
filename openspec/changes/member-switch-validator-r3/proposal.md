# Manual member-switch validator R3

The installed Companion catalog and backend legacy auth catalog have different
fingerprints. The current managed UI therefore cannot create a run even while
health and idle admission pass. Managed auth must consume the same trusted catalog
snapshot as the run, without rewriting historical catalog evidence.

Review the final R2 source and consumers for stale observations and incomplete
manual control paths. Fix only demonstrated violations. No live membership, OAuth,
canary, automatic rotation, or automatic recovery is authorized for validation.
