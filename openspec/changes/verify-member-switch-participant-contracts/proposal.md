# Verify member-switch participant contracts

Review the isolated durable-command candidate at the real API, database and
Companion serialization boundaries. Existing per-layer fake tests do not prove
that the participants accept each other's actual responses.

Keep the previous candidate immutable. No deployment, real accounts, browser
profiles, external requests or operational migrations are included. Preserve
manual commands and keep automatic rotation disconnected.

Fix only reproduced participant-contract defects. Do not replace the established
workflow or build a generic recovery engine.
