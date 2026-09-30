## Context

Codex Desktop can retain one local thread while its selected model moves between an OpenAI-compatible model source and the subscription upstream. OpenAI-compatible sources may emit plain `reasoning` response items with visible `reasoning_text` content and source-local IDs. The subscription Responses endpoint does not accept such replay items: a non-empty reasoning `content` array is rejected, and non-OpenAI reasoning IDs are not valid persisted-item references.

The existing account-neutral replay projection already removes reasoning items when replay crosses account ownership, which establishes that hidden reasoning state is not generally portable across upstream ownership boundaries. Cross-provider continuation needs the same safety principle without discarding visible assistant messages or tool history.

## Goals / Non-Goals

**Goals:**

- Prevent source-authored reasoning items from making a later subscription request invalid.
- Preserve valid subscription reasoning replay items.
- Preserve visible assistant/user/developer/tool history and ordering.
- Apply one consistent rule across all subscription Responses serialization paths.
- Keep model-source forwarding byte-for-byte behavior unchanged.

**Non-Goals:**

- Translate or synthesize hidden chain-of-thought between providers.
- Change model selection, session affinity, provider metadata, or UI labels.
- Strip all reasoning items unconditionally.
- Add persisted source provenance to conversation history.

## Decisions

### Identify non-portable reasoning from the item shape

A final subscription payload will omit a `type="reasoning"` input item when either:

1. its `content` member is present and not empty/null, or
2. its non-empty `id` is not a string beginning with `rs_`.

A reasoning item with absent/null/empty `content` and either no ID or a valid `rs_` ID remains unchanged. This preserves subscription-origin encrypted/stored reasoning while removing item shapes the subscription endpoint cannot accept.

Alternative considered: track the originating model source for every response item. That would add persisted state and coupling that is unnecessary because the incompatible wire shape is directly observable.

Alternative considered: rewrite Qwen reasoning into an empty `rs_` item. This is unsafe because the minted ID would not reference an item stored by the subscription upstream and produces a second invalid-request class.

### Normalize only final subscription egress dictionaries

The reusable `ResponsesRequest` model remains unchanged. A pure helper copies only the input list when removals are required and returns a removal count. It runs immediately before subscription serialization in:

- core Responses HTTP/websocket transport,
- direct websocket `response.create` serialization and size-guarded retry/fresh resend,
- HTTP bridge `response.create` preparation.

OpenAI-compatible model-source forwarding does not call this normalizer.

### Preserve user-visible continuity

Dropping a hidden reasoning item does not remove the assistant `message` item that follows it. Tool calls and tool outputs are untouched. This intentionally trades hidden cross-provider reasoning continuity for a valid visible conversation.

## Risks / Trade-offs

- **A future subscription reasoning format uses non-empty content** → The upstream currently rejects that exact shape. Regression tests pin the observed subscription contract; any upstream change can relax the filter later.
- **A source emits an `rs_`-looking ID** → Non-empty reasoning content still identifies and removes the incompatible item.
- **A malformed reasoning item is silently hidden** → Only reasoning items matching the two explicit invalid subscription shapes are omitted; unrelated malformed input continues through existing validation/error behavior.
- **One serializer misses the rule** → Share one helper and cover core HTTP, core websocket, direct websocket, fresh resend, and HTTP bridge paths with focused tests.

## Migration Plan

1. Add pure helper regression tests.
2. Add serialization-path tests that fail before the implementation.
3. Apply the helper to all subscription egress paths.
4. Run focused proxy suites, lint/type/architecture checks, and strict OpenSpec validation.
5. Qualify the Qwen → Astra same-thread scenario in an isolated environment before any production deployment.

Rollback is a code-only revert. No database, configuration, credential, or persisted-session migration is required.

## Open Questions

None. The observed upstream errors and existing account-neutral replay policy define the compatibility boundary.
