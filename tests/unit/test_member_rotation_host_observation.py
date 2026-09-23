from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from app.modules.member_switch import schemas
from scripts import member_rotation_host_observation as host
from tests.unit.test_member_rotation_controller import p4_provenance

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("failure", [None, "listeners", "inode", "device", "unmapped", "changed", "hash"])
def test_host_verifier_reads_kernel_identity_and_hash_without_launching_binary(tmp_path, monkeypatch, failure):
    binary = tmp_path / "synthetic-companion"
    binary.write_bytes(b"synthetic test binary")
    expected_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(schemas, "P4_TYPED_TELEMETRY_BINARY_SHA256", expected_hash)
    provenance = p4_provenance(binary_sha256=expected_hash)
    stat = binary.stat()
    commands = []

    def read(*args):
        commands.append(args)
        if args[-1] == "-t":
            return "123\n124" if failure == "listeners" else "123"
        if args[0] == "/bin/ps":
            return "second-start" if failure == "changed" and len(commands) > 3 else "first-start"
        inode = stat.st_ino + (1 if failure == "inode" else 0)
        device = stat.st_dev + (1 if failure == "device" else 0)
        path = "/different/executable" if failure == "unmapped" else str(binary)
        return f"p123\nftxt\ni{inode}\nD0x{device:x}\nn{path}"

    monkeypatch.setattr(host, "_read", read)
    if failure == "hash":
        binary.write_bytes(b"replaced test binary")
    if failure:
        with pytest.raises(ValueError):
            host.observe(binary, "synthetic-endpoint", provenance)
    else:
        observation = host.observe(binary, "synthetic-endpoint", provenance)
        assert observation.pid == 123 and observation.provenance == provenance
        assert observation.expires_at > datetime.now(timezone.utc)
    assert all(command[0] in {"/usr/sbin/lsof", "/bin/ps"} for command in commands)
