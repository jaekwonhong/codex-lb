# OpenCodex account / workspace-member identity-state contract

Status: normative boundary for extraction slice 3. Transport endpoint names and concrete adapter implementation are deferred to slice 6.

## Purpose

The Workspace Member Controller needs enough OpenCodex account identity and state to decide and recover workspace membership operations without becoming a second account router or credential store. This contract defines:

- the stable foreign identity used to bind a workspace member to an OpenCodex account;
- the ephemeral generation/revision fences used to reject stale decisions;
- the minimum normalized account-state projection the Controller may consume;
- the rules for mapping that foreign identity to workspace/member identities;
- the fail-closed rules for ambiguous, stale, missing or replaced account state.

## Identity namespaces are separate

The following identifiers MUST remain distinct. Similar values or labels MUST NOT be treated as interchangeable.

| Identifier | Owner | Meaning |
| --- | --- | --- |
| `workspace_id` | Controller | Stable Controller identity of one managed workspace. |
| `workspace_account_id` | Controller / membership source | Workspace-scoped upstream account identifier used by the existing membership protocol. It is **not** an OpenCodex account id. |
| `preset_id` | Controller | Stable Controller-local candidate/owner identity inside a workspace catalog. |
| `member_user_id` | Membership source | Upstream workspace member subject id (`user-*` in the current implementation). |
| `member_email` | Membership source | Normalized observed/contact identity. Supporting attribute only; never sufficient to bind an OpenCodex account. |
| `opencodex_account_id` | OpenCodex | Stable foreign key for one OpenCodex Codex-pool account, including the native-main identity where supported by the adapter. This is the primary cross-service account reference. |
| `account_selector` | OpenCodex configuration | Optional public exact-account namespace/selector that currently resolves to `opencodex_account_id`. It is an address/alias, not identity. |
| `account_alias` / `log_label` | OpenCodex | Operator-facing labels only. Never identity keys. |
| `credential_generation` | OpenCodex | Monotonic fence for the current credential lineage of a pool account. It is operation evidence, not member identity. |
| `main_identity_generation` | OpenCodex | Equivalent stale-identity fence for the native-main account snapshot. It is operation evidence, not member identity. |

Email, alias, display name, selector and log label MUST NOT be used alone to join Controller members to OpenCodex accounts.

## Durable member-to-account binding

The Controller's durable mapping is conceptually:

```text
WorkspaceMemberAccountBinding
  workspace_id
  workspace_account_id
  preset_id
  member_user_id
  member_email_normalized
  role = owner | member
  opencodex_account_id
```

The stable foreign key is `opencodex_account_id`. Credential generation and quota/health values do not belong in this durable identity row.

A binding is admissible only when:

1. the workspace/member tuple resolves to exactly one catalog identity;
2. the OpenCodex account id resolves to exactly one live account record;
3. the Controller has identity evidence that the account belongs to the intended member under the qualified enrollment/reconciliation flow;
4. no conflicting binding exists for the same workspace member; and
5. any reuse of one OpenCodex account across multiple workspace bindings is explicitly observed as the same subject rather than inferred from email/alias similarity.

The contract does not assume that an OpenCodex account can belong to only one workspace globally. Cross-workspace reuse is allowed only when the qualified identity evidence proves the same subject; otherwise it fails closed.

## Account-state projection

The OpenCodex adapter SHALL expose one normalized projection per requested exact account. A conceptual version-1 projection is:

```text
OpenCodexAccountStateV1
  schema_version = 1
  provider = "openai"
  account_id
  is_main
  selector?                 # current address hint only
  credential_generation?   # pool account fence
  main_identity_generation? # native-main fence
  observed_at
  has_credential
  needs_reauth
  paused
  health_status
  selection_state           # selectable | excluded | unknown
  exclusion_reasons[]
  quota_state               # available | exhausted | unknown
  quota_observed_at?
  quota_windows[]            # optional normalized decision evidence
  reset_credit_state?       # optional normalized evidence; writer remains OpenCodex
  state_revision             # opaque adapter-issued revision for the projected state
```

### Required semantics

- `account_id` is always the exact OpenCodex foreign identity requested by the Controller. The adapter MUST NOT silently substitute another pool account.
- Pool-account state includes the live `credential_generation` from the OpenCodex credential record when credential-scoped evidence is returned.
- Native-main state includes the live `main_identity_generation` when main-account identity-scoped evidence is returned.
- `state_revision` is opaque to the Controller. It identifies the exact normalized projection used for a decision and MAY be a monotonic revision or deterministic digest chosen by the adapter. The Controller compares it for equality only.
- `observed_at` is the adapter capture time, not a fabricated upstream time.
- `quota_observed_at` comes from OpenCodex-owned quota evidence when known. Missing or invalid timestamps do not become fresh by virtue of `observed_at`.
- `selection_state`, `exclusion_reasons`, `quota_state`, `health_status`, cooldown/reauth interpretation and reset-credit availability are normalized by OpenCodex. The Controller MUST NOT duplicate OpenCodex routing eligibility calculations from raw percentages.
- `quota_windows` may expose only the normalized windows required by membership policy, such as used percent/reset time/observation time. They are decision evidence, not a second routing state store.
- No access token, refresh token, bearer, cookie, inference API key, raw upstream quota response, or secret credential fingerprint is part of this projection.

## Selector rule

A configured exact selector can be useful for diagnostics and future account-targeted commands, but it is not durable identity.

- A selector MUST be resolved by OpenCodex to exactly one `account_id` at the time it is used.
- The Controller MUST bind and journal the resolved `account_id`, not merely the selector string.
- If a selector is removed or remapped, an existing durable member binding remains keyed by `account_id`; a command that uses the selector must first re-resolve it and prove it still names the bound account.
- Ambiguous, missing or remapped selectors fail closed for an exact-account command.

## Freshness and generation fences

### Read freshness

Any policy decision that requires live account state SHALL declare a Controller configuration value `account_state_max_age`. A projection is fresh only when:

```text
0 <= decision_time - observed_at <= account_state_max_age
```

This Controller freshness bound is an admission bound for membership effects. It does not redefine OpenCodex's own quota/cooldown freshness rules.

If quota evidence is required, `quota_observed_at` MUST also be present and the normalized OpenCodex `quota_state` MUST not be `unknown`. The Controller MAY apply a stricter membership-policy age to `quota_observed_at`, but it MUST NOT turn an OpenCodex `unknown` quota state into available/exhausted by recomputing raw windows.

### Credential/identity generation fence

When a decision depends on credential-scoped account state:

- a pool-account operation binds `account_id + credential_generation`;
- a native-main operation binds `account_id + main_identity_generation`;
- the fence is captured in immutable operation evidence;
- immediately before an account-management command or membership effect whose safety depends on that account evidence, the adapter MUST confirm the bound generation is still live or return a newer projection for full re-evaluation;
- a generation change invalidates the old evidence but does **not** change the durable member-to-account identity binding by itself.

A token refresh that advances generation therefore causes re-evaluation, not remapping of the workspace member.

## Immutable decision evidence

For every membership operation that used OpenCodex account state, the Controller SHALL retain a compact immutable evidence record sufficient to explain and fence that decision:

```text
AccountDecisionEvidenceV1
  provider
  account_id
  credential_generation? / main_identity_generation?
  state_revision
  observed_at
  quota_observed_at?
  selection_state
  quota_state
  needs_reauth
  paused
  relevant normalized quota-window evidence
```

This evidence belongs to the membership-operation journal. It is never refreshed in place and never becomes current account truth.

## Mapping and reconciliation rules

### Binding creation

A new or repaired binding requires exact Controller member identity (`workspace_id`, `workspace_account_id`, `preset_id`, `member_user_id`, normalized email) plus explicit OpenCodex account identity evidence. Email-only lookup is insufficient.

The initial adapter may support an operator/enrollment-assisted binding flow if OpenCodex's public account listing does not expose the workspace `user_id`. Such a flow MUST still end with an exact `opencodex_account_id` and durable Controller member identity; it MUST NOT persist an inference credential in the Controller.

### Binding read

When the Controller needs account state for a member, it requests the exact `opencodex_account_id`. If OpenCodex reports no such live account, more than one identity, or a state that cannot be safely projected, the account state is unavailable and mutation decisions requiring it fail closed.

### Binding repair

A changed email, alias or selector does not automatically rewrite a binding. A repair requires qualified identity reconciliation. A changed `member_user_id` for the same preset/workspace is an identity conflict until explicitly reconciled.

### Account removal/re-add

If an OpenCodex account id is removed, the binding is retained as a historical foreign reference but becomes unavailable for new mutations. Re-adding a credential under the same id with a new generation requires fresh identity reconciliation before account-sensitive membership mutation resumes when the adapter cannot prove subject continuity.

## Account-management command preconditions

Concrete command APIs are deferred, but any Controller -> OpenCodex account-management command SHALL carry enough precondition evidence to prevent stale-account writes:

```text
expected_account_id
expected_credential_generation? / expected_main_identity_generation?
expected_state_revision?
command_id
```

OpenCodex SHALL execute against the exact account or fail closed. It SHALL NOT redirect the command to another pool account. Unknown command outcome is reconciled by an exact state read before any retry.

## Fail-closed matrix

| Condition | Controller result |
| --- | --- |
| Exact account id missing | Block account-dependent membership mutation. |
| Account id resolves but identity binding is absent | Block; require explicit enrollment/reconciliation. |
| Email matches but user/member identity is unproven | Block; email is not a join key. |
| Selector missing/remapped | Block selector-targeted command until it resolves to the bound account id. |
| Projection older than `account_state_max_age` | Block and refresh through OpenCodex adapter. |
| Required quota state is `unknown` | Block quota-dependent replacement. |
| Required `quota_observed_at` missing/stale | Block quota-dependent replacement. |
| Credential/main identity generation changed | Re-read and re-evaluate; do not reuse old decision evidence. |
| State revision changed before an account-sensitive command | Re-read and re-evaluate the affected preconditions. |
| OpenCodex command result is unknown | Reconcile exact account state; do not blind-retry. |
| Multiple workspace identities appear to map to one account without same-subject proof | Block conflicting binding. |
| Controller has only a stale historical account snapshot | Never promote it to current truth. |

## Current OpenCodex capability evidence and adapter gap

The current OpenCodex source already has the primitives needed for this contract:

- stable pool account ids and a synthetic/native-main identity;
- exact account selector namespaces that fail closed rather than falling through;
- account pause/priority/auto-switch/pool strategy/sticky controls;
- quota snapshots with `updatedAt` and window/reset observations;
- generation-fenced pool credential records and a native-main identity generation;
- health/reauth state and account listing projections;
- exact generation checks before credential-scoped writes.

The ordinary account-list DTO intentionally does not expose every credential generation. The qualified OpenCodex checkpoint `af4f476` provides the narrow exact-account control-plane projection required by this contract, and the Controller consumes that projection without scraping internal credential files or inferring a generation from email/quota data. Rotation policy uses the normalized projected quota/selection/reset-credit state rather than recomputing routing eligibility from raw percentages.
