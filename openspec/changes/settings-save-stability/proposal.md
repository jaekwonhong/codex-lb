# Settings save and diagnostic outcome stability

Review the settings save/refresh and proxy endpoint diagnostic paths, independently
of the previously changed member-switch lifecycle. Preserve confirmed saved values
and their server version, handle UI-owned save rejections, and show the latest
endpoint diagnostic rather than retaining a stale success.

No backend, schema, routing policy, credentials, member switching or automation
changes. No real settings writes or proxy endpoint tests are used for validation.
