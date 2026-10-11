#!/usr/bin/env bash
# PC1-only, pre-authorized SSH path to PC2. No private key material here.
set -euo pipefail

identity="$HOME/.ssh/deskflow_pc2_ed25519"
if [[ ! -r "$identity" ]]; then
  printf 'PC2 SSH: missing PC1 identity file\n' >&2
  exit 2
fi

exec ssh -i "$identity" \
  -o IdentitiesOnly=yes \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  -o HostKeyAlias=100.120.143.35 \
  -o ConnectTimeout=8 \
  -T jaekw@jaekwonhong "$@"
