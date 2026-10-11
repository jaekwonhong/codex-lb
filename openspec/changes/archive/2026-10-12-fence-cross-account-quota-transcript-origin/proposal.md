## Why

The October 11 PC2 Beta quota incident left an old, hard-owner thread unable to
switch OAuth accounts when the required full-history evidence was missing
(`anchor_metadata_missing`). That safety refusal is correct when no complete
history is available, but a completed, durable transcript can reconstruct some
delta-only turns without losing context. The current definitive owner-quota
path already attempts this reconstruction. Unlike the same-owner fresh
WebSocket reattach path, however, its positive shared relocation verdict does
not independently prove that the transcript belongs to the exact
session/account/response owner or is still the uninterrupted latest turn.

## What Changes

Gate **transcript-backed** cross-account quota relocation on the same
completed, same-owner/same-session event-chain proof as reattachment, plus the
repository's read-only latest-operation-head proof. Apply this only *after*
the shared relocation verdict has said the rebuilt body is safe, and only when
the other account would actually receive reconstructed durable items.

When the candidate transcript has a missing/mismatched owner, incomplete or
foreign terminal, stale response anchor, uncertain newer operation, or a failed
read-only head check, retain the owner-bound local-history recovery refusal.
Full client-resend moves already independently proven by the common replay
verdict stay eligible. No additional routing setting or schema change.

## Out of Scope

- Reconstructing a historical thread whose durable records have already been
  purged; missing evidence must stay a local-history recovery request.
- Forcing real quota consumption or changing stable routing, PC2 always_http,
  tokens, member management or WMC.
- Automatically moving accepted/partially visible responses or hosted tools.
