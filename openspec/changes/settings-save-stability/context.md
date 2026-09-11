# Scope and evidence

Parent operational main: 52d70479c8c968fb5a48b725e931bb6c5981c682.
The existing settings API returns a validated full snapshot and optimistic-concurrency
version. The previous UI discards that response and relies entirely on another GET.
Settings cards invoke an event-only parent save callback; the hook already publishes
errors, but the page does not consume rejected promises. Endpoint diagnostics retain
an old success when a later request rejects.

Use existing query/mutation ownership and error UI, not a new persistence or retry
framework. For example, version 10 -> successful PUT version 11 -> failed GET must
leave the confirmed version 11 on screen. Existing failed-read indication remains.
Run only synthetic requests and immutable image/file checks; never use live settings
updates, endpoint tests, real OAuth or membership changes as verification.
