"""Read-only macOS listener/executable verification; signs a 30-second receipt.

Run externally with an operator-managed Ed25519 private key. The backend receives
only the raw public key. This command neither installs keys nor enables rotation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.modules.member_switch.runtime_attestation import (
    HostRuntimeObservation,
    SignedHostObservation,
    observation_bytes,
)
from app.modules.member_switch.schemas import CompanionTypedTelemetryProvenance


def _read(*args: str) -> str:
    return subprocess.check_output(args, text=True, timeout=10).strip()


def process_identity(binary: Path) -> tuple[int, str, int, int, int, int, int]:
    listeners = set(_read("/usr/sbin/lsof", "-nP", "-iTCP:53418", "-sTCP:LISTEN", "-t").splitlines())
    if len(listeners) != 1:
        raise ValueError("companion_listener_ambiguous")
    pid = int(listeners.pop())
    started = _read("/bin/ps", "-p", str(pid), "-o", "lstart=")
    stat = binary.stat()
    # Match the kernel's mapped text vnode, not just argv or an on-disk pathname.
    mapped = _read("/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-d", "txt", "-F", "finD")
    records: list[dict[str, str]] = []
    for line in mapped.splitlines():
        if line.startswith("f"):
            records.append({})
        elif records and line[:1] in {"i", "n", "D"}:
            records[-1][line[0]] = line[1:]
    matches = [r for r in records if r.get("n") == str(binary)]
    if not started or len(matches) != 1:
        raise ValueError("companion_executable_unmapped")
    mapped_file = matches[0]
    if int(mapped_file["i"]) != stat.st_ino or int(mapped_file["D"], 16) != stat.st_dev:
        raise ValueError("companion_executable_replaced")
    return pid, started, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def observe(binary: Path, endpoint: str, provenance: CompanionTypedTelemetryProvenance) -> HostRuntimeObservation:
    if not provenance.qualified:
        raise ValueError("companion_release_not_qualified")
    binary = binary.resolve(strict=True)
    observed_at = datetime.now(timezone.utc)
    before = process_identity(binary)
    with binary.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = process_identity(binary)
    if before != after or digest != provenance.binary_sha256:
        raise ValueError("companion_runtime_changed_or_hash_mismatch")
    if datetime.now(timezone.utc) >= observed_at + timedelta(seconds=30):
        raise ValueError("companion_verification_timed_out")
    return HostRuntimeObservation(
        endpoint=endpoint,
        provenance=provenance,
        pid=before[0],
        process_started=before[1],
        executable_device=before[2],
        executable_inode=before[3],
        observed_at=observed_at,
        expires_at=observed_at + timedelta(seconds=30),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--endpoint", required=True, help="Exact backend-configured account-pool URL")
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True, help="External signer raw Ed25519 key")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    provenance = CompanionTypedTelemetryProvenance.model_validate_json(args.provenance.read_bytes())
    observation = observe(args.binary, args.endpoint, provenance)
    key = Ed25519PrivateKey.from_private_bytes(args.private_key.read_bytes())
    signed = SignedHostObservation(
        observation=observation,
        signature=base64.b64encode(key.sign(observation_bytes(observation))).decode(),
    )
    descriptor, temporary = tempfile.mkstemp(dir=args.output.parent, prefix=".host-observation-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(signed.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
