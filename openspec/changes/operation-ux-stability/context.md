# Context

This change is frontend-only. Existing backend authorization, idempotency, mutation
semantics, database schema, Companion behavior, and automatic-rotation state are
unchanged. Validation uses synthetic/local API responses; no live account, firewall,
model-source, automation, member-switch, OAuth, or proxy mutation is required.
