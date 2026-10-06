# Standalone Workspace Member Controller

The standalone Controller is a control-plane process. It does not proxy inference traffic and it does not own ChatGPT/Codex credentials or account-pool routing. OpenCodex remains the account-state authority; the Controller owns workspace/member observation, membership policy and the durable membership-operation boundary.

## Configuration

The process reads only `WMC_` environment variables. Secrets can be supplied directly or from owner-only token files; do not configure both forms for the same secret.

Required values:

```text
WMC_DATABASE_URL=postgresql+asyncpg://...
WMC_ACCOUNT_BINDINGS_PATH=/absolute/path/account-bindings.json
WMC_ADMIN_TOKEN_FILE=/absolute/path/controller-admin-token
WMC_OPENCODEX_ADMIN_TOKEN_FILE=/absolute/path/opencodex-admin-token
```

Optional values and defaults:

```text
WMC_HOST=127.0.0.1
WMC_PORT=2461
WMC_COMPANION_BASE_URL=http://127.0.0.1:53418/member-switch/v1
WMC_OPENCODEX_MANAGEMENT_BASE_URL=http://127.0.0.1:10101
```

The Controller listener is intentionally loopback-only in this qualification stage. Do not expose its bearer admin surface directly to the LAN. A later deployment may add an authenticated TLS front end without changing the Controller's internal ownership boundary.

Token files must not be group/world readable or writable (`0600` is the expected mode). Plain HTTP OpenCodex management URLs are accepted only for localhost/loopback or `host.docker.internal`.

## Explicit account bindings

`WMC_ACCOUNT_BINDINGS_PATH` points to the explicit member-to-OpenCodex identity map. Use `config/workspace-member-controller.bindings.example.json` as the shape reference. The Controller never creates a binding from matching email, alias, selector, old Codex-LB account id, or workspace id. Startup verifies every binding against the current Companion catalog and then reads the exact `opencodexAccountId` through OpenCodex's Controller account-state projection.

An empty `bindings` array is valid for read-only shadow qualification. Any later quota-driven membership mutation for an unbound member fails closed until a qualified exact binding is supplied.

## Startup validation

Before serving requests the process validates all of the following:

- the shared migration database is reachable;
- all Controller-owned legacy migration tables and required columns exist;
- the Companion catalog endpoint is reachable and schema-valid;
- the explicit binding file is bounded, schema-valid and free of conflicting account subjects;
- every configured binding matches one exact catalog workspace/member identity;
- every referenced OpenCodex account id resolves through the exact non-secret account-state endpoint.

Validation can be run without starting a listener:

```text
workspace-member-controller --validate
```

## HTTP surface

Unauthenticated health endpoints:

```text
GET /health/live
GET /health/ready
```

The existing read-only Controller API is protected by the Controller admin bearer token:

```text
GET /v1/catalog
GET /v1/status
GET /v1/workspaces/{workspace_id}/observation
```

No membership mutation HTTP route is exposed by this package yet. Mutation activation is reserved for the separately qualified canary/cutover stages.

## Run

```text
workspace-member-controller
```

The process runs one Uvicorn worker on `127.0.0.1:2461` by default. It does not import or start Codex-LB's proxy, usage schedulers, account-pool workers, dashboard authentication stack, or inference request handlers.
