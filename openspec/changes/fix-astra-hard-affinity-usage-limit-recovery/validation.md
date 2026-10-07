# fork/main integration validation — 2026-10-07

## Integration boundary

This change is a selective patch-port onto the user's fork `main`, not a merge
of the production-Beta branch history.

- Base: `fork/main` at `e14035005`
- Integration branch: `integrate/astra-continuity-main-port-20261007`
- Production reference: `fix/production-beta-astra-local-history-auto-recovery-20261007`
- Qualified production runtime source: `e9cca2448`

The production branch and `fork/main` have substantial parallel history. A
full-history merge would import unrelated historical routing, release, and GLM
work. The integration therefore ports only the dependencies required by the
final Astra owner-quota relocation contract and keeps main-specific behavior
where the production-only layer does not exist.

## Ported prerequisites

The main port includes the portable Codex full-resend/replay-safety chain needed
to prove that a request can cross accounts without losing prior context:

- portable lite-session reconstruction (`80ecccbfd` source change);
- live WebSocket terminal-item replay;
- Codex full-resend developer-hook recognition and transport metadata;
- unanswered-turn, untagged-group, and historical-developer-group handling.

It also carries the final owner-quota contracts:

- definitive quota provenance is emitted only for ownership/continuity-constrained
  required-account selection;
- definitive quota provenance survives owner forwarding and reconnect boundaries;
- direct HTTP selection-time quota and post-dispatch quota both pass through the
  shared `decide_relocation` policy;
- HTTP-bridge relocation re-fences an existing durable operation on the
  replacement owner before dispatch;
- generic configured `required_account_id` routing keeps its non-continuity
  semantics.

The direct-stream path additionally needs the small transport-independent
`OwnerRecoveryBudget` boundary originally introduced as part of the wider
production owner-interruption work. Only `app/core/balancer/recovery.py` and the
corresponding direct-stream retry budget hunks were ported. Without this bound,
a selection-time definitive owner-quota result repeatedly selected the same
owner until the entire request-generation budget expired; with it, the focused
selection-time relocation regression completes in about 2.6 seconds and enters
the shared relocation verdict.

## Intentionally not ported

- The production-Beta read-only `assess_owner_recovery` advisory preflight is
  not present on `fork/main`. Therefore the later stale-cooldown advisory fix is
  not applicable to this main topology.
- The production local-history-recovery UX helpers are also not present on
  `fork/main`. After the shared relocation verdict refuses a move, main keeps
  its existing `previous_response_owner_unavailable` fail-closed result instead
  of importing that Beta-only UX layer. The relocation policy decision itself
  is unchanged.
- The broader owner-interruption implementation that originally introduced
  `OwnerRecoveryBudget` was not imported wholesale; unrelated HTTP-bridge
  advisory, admission, and owner-recovery surfaces remain on main's existing
  implementation.
- GLM compaction commits from the production branch are excluded from this
  Astra port. GLM qualification and catalog policy are maintained separately.

The production shared-quota-contract commit was not replayed as a whole because
`fork/main` already contains main-adapted equivalents for message-only usage
limit recognition, definitive quota markers, and shared relocation policy.

## Focused verification

Replay/full-resend safety:

```text
953 passed, 959 deselected
```

This covers replay safety, replay relocation, HTTP-bridge full resend,
developer-hook grouping, transport metadata, WebSocket terminal replay, and the
parameterized account-neutral projection/refusal cases.

Quota/forwarding/load-balancer contracts:

```text
244 passed, 1267 deselected
```

This covers required-owner quota classification, generic required-account
isolation, definitive quota forwarding, owner-forward provenance, shared
relocation, and selection-time quota handling.

Critical end-to-end scenarios:

```text
3 passed
```

The three explicit gates are:

1. HTTP-bridge owner `usage_limit_reached` -> account-neutral full resend ->
   replacement-owner continuation with durable-operation re-fencing;
2. Astra-shaped inline-image terminal quota/execution evidence remains
   owner-bound and fail-closed;
3. direct HTTP selection-time definitive owner quota invokes the shared
   relocation verdict and successfully selects the replacement account.

Codex captured-body fixtures:

```text
153 passed
```

All retained production dispatch shapes still validate after the replay-safety
port.

Additional forwarding-only coverage passed 56/56. The parameterized durable
full-resend projection suite passed 12/12 after the main-native fail-closed
adaptation.

## Static gates

- `ruff` on every Python file changed from `fork/main`: PASS
- repository-wide `ty check`: PASS
- `git diff --check fork/main..HEAD`: PASS
- Python compile checks for the selectively added recovery/retry modules: PASS

The focused suites emit the repository's existing Starlette deprecation warning.
The replay suite also emits several non-failing test-teardown
`AdmissionLease ... without release()` diagnostics; no assertion or test gate
fails because of those messages.

## Runtime scope

This source integration does not redeploy or alter the already-qualified PC1
Beta runtime. Production Beta remains on the exact `e9cca2448` image qualified
separately, and Stable remains untouched. This validation concerns only making
the same structural recovery contract available on the user's fork `main`
without importing the production branch's unrelated history.

## Promotion rule

Promote this integration to the user's `fork/main` only if:

1. the branch still descends directly from the current `fork/main` after a fresh
   fetch;
2. strict OpenSpec validation passes on the exact remote integration commit;
3. the integration worktree is clean and all focused/static gates above remain
   green.

No upstream `Soju06/codex-lb` branch or PR is part of this integration.
