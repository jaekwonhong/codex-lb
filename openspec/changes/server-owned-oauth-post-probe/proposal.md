# Change: Server-owned OAuth post-registration Force Probe

## Why
The dashboard currently starts Force Probe as a browser-side follow-up after a successful current-member OAuth enrollment. A real workspace-2 registration completed with an exact `auth_account_id`, but no automatic `/probe` request was sent; quota exhaustion became visible only after the operator manually probed the account. Browser lifecycle/request ownership must not determine whether post-registration usage is refreshed.

## What changes
- Move post-registration Force Probe ownership from the frontend to the server-owned OAuth enrollment endpoints.
- Reuse the same account Force Probe implementation as the manual account probe route, including credential refresh, usage force-refresh, proxy-health settlement, and audit logging.
- Persist a durable single-attempt claim before Probe and the terminal diagnostic afterward, so concurrent/recovered requests never automatically replay a post-registration Probe; an abandoned attempt settles as outcome-unknown.
- Keep OAuth completion authoritative even when the post-probe cannot run or fails.
- Make the dashboard display the server-returned diagnostic and invalidate account/dashboard read caches after terminal enrollment; it no longer issues the probe POST itself.

## Compatibility
The new terminal enrollment diagnostic is optional in persisted JSON. Existing enrollment rows remain readable without a database migration.
