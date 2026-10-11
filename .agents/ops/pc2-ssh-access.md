# PC2 SSH Access from PC1 DevSpace

Use for user-authorized PC2 tasks. Read this document when a session needs
to reach PC2; the user should **not** need to repeat the connection path.

## Verified topology — 2026-10-11

- Origin: PC1 DevSpace checkout `C:\Retention_Infra\codex-lb` (Windows).
- Target: PC2, Tailscale MagicDNS name `jaekwonhong`.
- Account: `jaekw`.
- Existing dedicated key on **PC1 only**: `~/.ssh/deskflow_pc2_ed25519`.
- Known host identity: stored on PC1 under `100.120.143.35` from a previously
  verified Tailscale peer. The address is a host-key alias, not a permanent
  routing dependency.
- Connection: `bash .agents/ops/ssh-pc2.sh hostname`.
- Verified response: `jaekwonhong`. Public-key auth succeeded without
  additional SSH approval or password entry on 2026-10-11.

The script works from both the main checkout and any project worktree, because
its credentials stay in the PC1 user's SSH directory. To run another command,
pass its arguments, e.g. `bash .agents/ops/ssh-pc2.sh whoami`.
The wrapper uses SSH `-n` to close stdin. Without it, Codex CLI can wait
indefinitely at `Reading additional input from stdin...` in DevSpace. For
intentionally piped input, use a separate, explicitly reviewed SSH invocation.

## Operational boundaries

- Keep host key checking enabled and the existing private key confined to PC1.
- Do not copy a private key to Mac, attach it to a chat, or store it in Git.
- Do not open port 22 to the public internet or weaken server SSH settings.
- Confirm target `hostname` and Tailscale peer identity after re-enrollment.
- The Mac-specific *temporary* SSH key created on 2026-10-11 is separate and
  must be cleaned up. Do not replace this PC1 key with it.
- PC2's Codex-LB Beta uses port 2456, and the PC2 API-key policy is
  `always_http` after a WebSocket stream incident. Preserve that policy.
- At 17:58 KST on 2026-10-11, PC2's `gpt-6.1-sol`/`high` request reached
  Beta over HTTP but received `usage_limit_reached` (429).
- At approximately 18:32 and 18:36 KST, **PC2 Windows** Desktop-bundled
  Codex CLI `0.162.0-alpha.17.2` completed a new conversation and a
  `codex exec resume` turn. Both Beta request-log rows are `success` over
  HTTP with reasoning `high`. The server classified both as
  `request_stage=first_turn`; this proves CLI resume, **not** restoration
  of a missing server-side `previous_response_id` owner.
- At that time all six Team OAuth rows warned `reauth_required` even though
  stored access-token expirations were still in the future. Distinguish
  temporary token routability from safe long-term refresh; coordinate
  reauthentication with the owning account manager rather than looping 429
  probes or rotating tokens independently in multiple services.
- The Mac-only temporary SSH key was deleted, and the PC2 auto-cleanup
  scheduled task disappeared after its 18:31 KST trigger. The original
  PC1-to-PC2 permanent key continued to authenticate successfully.
- An older PC2 npm CLI `0.130.0-alpha.5` could not parse the current
  `service_tier` and model catalog. Use the tested Desktop-bundled binary
  when doing controlled client verification; do not rewrite user profiles.
- After promoting Beta recovery commit `a3dc6eba0`, at 21:04 and 21:05 KST,
  PC2's Desktop-bundled CLI `0.162.0-alpha.17.2` completed a real fresh turn
  and same-thread resume for `gpt-6.1-sol` / `high`. Beta DB confirmed two
  `success` request rows, upstream transport `http`, no error. A CLI-only
  `-c service_tier=fast` override was used; the profile was not edited.
- Both post-promotion requests were logged as `request_stage=first_turn`,
  so the earlier WebSocket previous-response owner failure was not reproduced
  in real operation. The native WS failure-phase diagnostics remain enabled.

## New-session recovery

1. Open PC1 DevSpace project `C:\Retention_Infra\codex-lb`.
2. Follow the `AGENTS.md` reference here.
3. Run `bash .agents/ops/ssh-pc2.sh hostname`.
4. Proceed with the user-authorized PC2 task, retaining host-key verification.
