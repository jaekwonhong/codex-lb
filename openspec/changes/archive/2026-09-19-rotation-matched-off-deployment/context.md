# Scope and outcome

This change covers the authorized matched OFF deployment, external signer, current pinned host operations and Q4 release decision. It does not require forcing a live canary. Its normative requirements are in the delta spec; durable context is in `../../../specs/member-switch-commands/off-deployment-20260919.md`.

Backend image `c409eac1...` and Companion `2.11.48-canary.1` were deployed OFF after current-data DB qualification and independent review. The signer uses a dedicated installed runtime and a private host key; the backend receives only readonly public observations. Automatic renewal and backend verification passed.

Current root operation wrappers retain older beta.7 pins, so separate `current_ops.py` tooling pins this qualified deployment. It preserves predecessor storage/configuration/sentinel, journals before fencing and retains a review lock if candidate stop or recovery cannot be proven. Production remains unchanged while the same transaction is qualified against a retained private current-data DB copy.

Q3 was evaluated but is NOT RUN / NOT ADMITTED: actual same-fetch data is Weekly-only, lacking mandatory 5H retention input. A primary duration of 604800 seconds is Weekly regardless of slot position. The implementation must not fabricate missing 5H data. The Q4 decision is NO-GO for automatic release and continued matched OFF operation, with all canary budget and execution records preserved. The umbrella feature change retains the unperformed conditional canary task.

The prior host-access obstruction is resolved and is no longer a release-decision blocker. Evidence and full operational limitations live in `/Users/nowtech/Documents/codex-lb-server/artifacts/rotation-off-deployment-20260919/release-decision.md`. No live replacement, production recreation, full reboot, commit or merge is claimed.
