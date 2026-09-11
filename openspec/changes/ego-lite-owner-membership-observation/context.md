# Owner membership observation context

`목록 불러오기` / `목록 새로고침` is an explicit read of the current workspace member and invite lists. It is separate from later membership mutations.

Each workspace owner email is resolved through the managed account pool. The stable account ID selects exactly one Ego Lite profile (`CodexLB-<accountId>`) and one deterministic owner Task Space (`codex-lb-owner-<accountId>`). The browser session email is verified before the workspace admin APIs are read. A missing login or wrong identity is surfaced on that exact Task Space; another browser/profile is never substituted.

This change deliberately leaves `DeleteAsync`, `InviteAsync`, and `CancelInviteAsync` on the existing owner-CDP path. It removes CDP from list loading, not from the entire membership mutation lifecycle.

Independent review found one mixed-version gap: OAuth-only current-member validation also calls membership observation. It therefore shares the same capability gate so a stale Companion cannot restore owner CDP reads on that path.
