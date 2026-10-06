# Single-workspace mutation canary preflight — 2026-10-07

## Scope

This document records **preparation only** for the later single-workspace mutation canary. No membership effect was executed during this step.

The chosen canary workspace is `cdp-2` because its current observation was authoritative, complete, owner-verified, non-ambiguous, and contained exactly one known non-owner member. Other observed workspaces were excluded from canary selection because one already had an owner-membership observation error and another contained an unknown member.

## Prepared safety boundary

The canary path is deliberately separate from production mutation routing:

- the effect adapter can call only the existing qualified Companion `/canary-operations` path;
- it does not fall back to the normal operation endpoint;
- durable Controller command claim/no-replay journal ownership is acquired before the canary effect;
- a lost start response is recoverable only by the original client-flow/operation identity;
- reconciliation never resends the start mutation;
- success requires the exact outgoing-member absence trace, invitation issuance, final membership confirmation, and no unsafe response-capture state;
- pre-membership authoritative failure may close as non-effect;
- ambiguous/partial post-effect evidence remains outcome-unknown and is not finalized as success;
- Companion admission and the full qualified capability set are rechecked after durable claim and before the canary start;
- stale/not-ready previews settle as authoritative non-effect rather than being sent.

The one-shot runner is phase-separated:

1. `preflight` — read-only; proves idle scope, authoritative current membership, exact target identity, and exact OpenCodex bindings for both current and target subjects.
2. `forward` — explicit mutation authorization required; executes only the forward canary and writes a mode-`0600` state handoff. It **does not** perform rollback in the same invocation.
3. `rollback` — separately authorized; requires the retained handoff, proves the target is still current, revalidates both exact OpenCodex bindings, and only then attempts the reverse canary.

This separation is required so the user can inspect the forward result before authorizing rollback and so an ambiguous forward outcome cannot trigger an automatic reverse effect.

## Exact OpenCodex account prerequisite

The canary runner does not infer an OpenCodex account from email, alias, selector, old Codex-LB account id, or workspace id. Both the current and target workspace member must already have explicit `WorkspaceMemberAccountBinding` entries, and the exact referenced OpenCodex account-state projection must report a credential that is present, administratively paused for routing isolation, and not in reauthentication-required state. The canary membership effect is carried by Companion, so making these accounts inference-selectable would add data-plane exposure without strengthening membership evidence.

The live preflight on 2026-10-07 stopped before any durable claim or effect because the current `cdp-2` member had no explicit OpenCodex account binding. The active/pending membership journal snapshot was unchanged before and after preflight, Companion admission remained `ready`, and no canary handoff state file was created.

A read-only OpenCodex account-list inspection also showed that the current native pool does not yet contain an explicitly qualified account for either the current or selected target workspace member. This observation is supporting evidence only; the decisive gate remains the absence of explicit bindings.

## 11-1 conclusion

Canary implementation and no-replay preparation are qualified, but the **actual forward canary is blocked** until both selected subjects are onboarded into the OpenCodex native account pool and explicit exact bindings are supplied. The blocker is intentional and fail-closed. Do not bypass it by binding based only on matching email or legacy Codex-LB identity.
