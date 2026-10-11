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

## Operational boundaries

- Keep host key checking enabled and the existing private key confined to PC1.
- Do not copy a private key to Mac, attach it to a chat, or store it in Git.
- Do not open port 22 to the public internet or weaken server SSH settings.
- Confirm target `hostname` and Tailscale peer identity after re-enrollment.
- The Mac-specific *temporary* SSH key created on 2026-10-11 is separate and
  must be cleaned up. Do not replace this PC1 key with it.
- PC2's Codex-LB Beta uses port 2456, and the PC2 API-key policy is
  `always_http` after a WebSocket stream incident. Preserve that policy.
- On 2026-10-11, PC2 Desktop-bundled Codex CLI `0.162.0-alpha.17.2` reached
  Beta with `gpt-6.1-sol`/`high` over HTTP but received upstream quota
  `usage_limit_reached` (429). Recheck available quota before any repeat.
- An older PC2 npm CLI `0.130.0-alpha.5` could not parse the current
  `service_tier` and model catalog. Use the tested Desktop-bundled binary
  when doing controlled client verification; do not rewrite user profiles.

## New-session recovery

1. Open PC1 DevSpace project `C:\Retention_Infra\codex-lb`.
2. Follow the `AGENTS.md` reference here.
3. Run `bash .agents/ops/ssh-pc2.sh hostname`.
4. Proceed with the user-authorized PC2 task, retaining host-key verification.
