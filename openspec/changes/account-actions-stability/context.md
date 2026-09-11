# Scope and failure boundaries

Parent operational main b30f3f6 and settings-save-stability source/static are the
review baseline. This is a different scope from member-switch lifecycle and
settings cache publication. Inspect both API-key deletion consumers (/apis and
the Settings section), not just a shared helper. Backend write authorization
remains authoritative; missing UI gating is not evidence of authorization bypass.

Keep existing DELETE history semantics and account-scoped usage redemption IDs.
A failed response does not prove absence of a durable effect. Do not automatically
repeat requests, restore operational DB state, or enable rotation/canary tests.
Use only fake HTTP effects; runtime inspection is read-only and deployment is
beta-only with immutable artifacts and predecessor preservation.
