#!/usr/bin/env python3
"""Restart-safe first-start gate for an admitted beta.9 Q2 candidate image.

Unlike the historical Q2 gate, this module does not hard-code the candidate
image digest. The caller must provide the exact image/source/tree tuple after
the immutable build exists. The gate pathname is then derived from the full
image digest, so a new candidate can never consume the old Q2 sentinel.

This module does not create, start, stop, rename, or publish host ports. It
builds the exact Docker Config gate delta, validates container provenance and
PID1/sentinel identity, and atomically publishes or removes the sentinel for an
already-created candidate container.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from typing import Any, cast

PACKAGE_VERSION = "1.25.0-beta.9"
UPSTREAM_SOURCE_SHA = "69f128afcbc616d9f8e924ca6583f7031d75cf82"
Q2_LIVE_SOURCE_SHA = "0f75aa03f51cd8fb2dc8600374046f844cac2756"

ORIGINAL_ENTRYPOINT: None = None
ORIGINAL_CMD = ["/app/scripts/docker-entrypoint.sh"]
ORIGINAL_ENTRYPOINT_PATH = "/app/scripts/docker-entrypoint.sh"
ORIGINAL_ENTRYPOINT_SHA256 = "c2203ee0402234761ba343ca8621265a0d5240d22de5754386232260a19489ca"
APP_PID1_ARGV = ["python", "-m", "app.cli", "--host", "0.0.0.0", "--port", "2455"]

GATE_DIR = "/var/lib/codex-lb"
GATE_PREFIX = ".beta9-q2-start-gate-"
GATE_SUFFIX = "-v1"
GATE_UID = 1000
GATE_GID = 1000
GATE_MODE = 0o600
GATE_ENTRYPOINT = ["/bin/sh"]
GATE_ARGV0 = "beta9-q2-start-gate"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
TOKEN_RE = re.compile(r"[a-f0-9]{64}\Z")
NONCE_RE = re.compile(r"[a-f0-9]{32}\Z")


class Failure(RuntimeError):
    pass


class AmbiguousGateRelease(Failure):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def _normalized_image_sha256(value: str) -> str:
    raw = value.removeprefix("sha256:")
    require(_SHA256_RE.fullmatch(raw) is not None, "candidate image SHA-256 is invalid")
    return f"sha256:{raw}"


def _git_sha(value: str, label: str) -> str:
    require(_GIT_SHA_RE.fullmatch(value) is not None, f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    image_sha256: str
    source_sha: str
    source_tree_sha: str

    @classmethod
    def admitted(cls, *, image_sha256: str, source_sha: str, source_tree_sha: str) -> CandidateIdentity:
        return cls(
            image_sha256=_normalized_image_sha256(image_sha256),
            source_sha=_git_sha(source_sha, "candidate source SHA"),
            source_tree_sha=_git_sha(source_tree_sha, "candidate source tree SHA"),
        )

    @property
    def image_hex(self) -> str:
        return self.image_sha256.removeprefix("sha256:")

    @property
    def gate_name(self) -> str:
        return f"{GATE_PREFIX}{self.image_hex}{GATE_SUFFIX}"

    @property
    def gate_path(self) -> str:
        return f"{GATE_DIR}/{self.gate_name}"


def new_token() -> str:
    token = secrets.token_hex(32)
    require(TOKEN_RE.fullmatch(token) is not None, "candidate gate token generation failed")
    return token


def new_nonce() -> str:
    nonce = secrets.token_hex(16)
    require(NONCE_RE.fullmatch(nonce) is not None, "candidate gate publication nonce generation failed")
    return nonce


def _token_bytes(token: str) -> bytes:
    require(TOKEN_RE.fullmatch(token) is not None, "candidate gate token is invalid")
    return (token + "\n").encode("ascii")


def token_sha256(token: str) -> str:
    return hashlib.sha256(_token_bytes(token)).hexdigest()


def wrapper_script(identity: CandidateIdentity, token: str) -> str:
    _token_bytes(token)
    validator = (
        "import os,stat,sys; "
        f"p={identity.gate_path!r}; expected={(token + chr(10)).encode('ascii')!r}; "
        "flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0); "
        "\ntry: fd=os.open(p,flags)\n"
        "except FileNotFoundError: raise SystemExit(3)\n"
        "try:\n"
        " s=os.fstat(fd); data=b''\n"
        " while True:\n"
        "  block=os.read(fd,4096)\n"
        "  if not block: break\n"
        "  data+=block\n"
        " if not stat.S_ISREG(s.st_mode): raise SystemExit(21)\n"
        f" if stat.S_IMODE(s.st_mode)!={GATE_MODE}: raise SystemExit(22)\n"
        f" if s.st_uid!={GATE_UID} or s.st_gid!={GATE_GID}: raise SystemExit(23)\n"
        " if data!=expected: raise SystemExit(24)\n"
        "finally: os.close(fd)"
    )
    payload = base64.b64encode(validator.encode("utf-8")).decode("ascii")
    loader = f"import base64;exec(base64.b64decode('{payload}'))"
    return (
        "set -eu; "
        "trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM; "
        "while :; do "
        f"if /opt/venv/bin/python -c {json.dumps(loader)}; then rc=0; else rc=$?; fi; "
        'if [ "$rc" -eq 0 ]; then break; fi; '
        'if [ "$rc" -ne 3 ]; then exit "$rc"; fi; '
        "sleep 0.05; "
        "done; "
        "trap - HUP INT TERM; "
        f"exec {ORIGINAL_ENTRYPOINT_PATH}"
    )


def gate_cmd(identity: CandidateIdentity, token: str) -> list[str]:
    return ["-ceu", wrapper_script(identity, token), GATE_ARGV0]


def wrapper_sha256(identity: CandidateIdentity, token: str) -> str:
    return hashlib.sha256(wrapper_script(identity, token).encode("utf-8")).hexdigest()


def _run(args: list[str], *, input_text: str | None = None, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Failure("candidate gate command unavailable") from exc
    if result.returncode != 0:
        raise Failure("candidate gate command failed")
    return result


def _docker_exec(container_id: str, command: list[str], *, input_text: str | None = None) -> str:
    args = ["docker", "exec"]
    if input_text is not None:
        args.append("-i")
    args.extend([container_id, *command])
    return _run(args, input_text=input_text).stdout


def _docker_inspect(container_id: str) -> dict[str, Any]:
    raw = _run(["docker", "inspect", container_id]).stdout
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Failure("candidate container inspect is malformed") from exc
    require(
        isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
        "candidate inspect is malformed",
    )
    return cast(dict[str, Any], value[0])


def _docker_image_inspect(image_sha256: str) -> dict[str, Any]:
    raw = _run(["docker", "image", "inspect", image_sha256]).stdout
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Failure("candidate image inspect is malformed") from exc
    require(
        isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
        "candidate image inspect is malformed",
    )
    return cast(dict[str, Any], value[0])


def _expected_provenance_labels(identity: CandidateIdentity) -> dict[str, str]:
    return {
        "org.opencontainers.image.version": PACKAGE_VERSION,
        "org.opencontainers.image.revision": identity.source_sha,
        "codex-lb.source-tree": identity.source_tree_sha,
        "codex-lb.upstream-source": UPSTREAM_SOURCE_SHA,
        "codex-lb.q2-live-source": Q2_LIVE_SOURCE_SHA,
    }


def validate_candidate_image(identity: CandidateIdentity) -> dict[str, Any]:
    """Bind source/tree provenance to immutable image config, not overrideable container labels."""

    view = _docker_image_inspect(identity.image_sha256)
    require(view.get("Id") == identity.image_sha256, "candidate image identity mismatch")
    config_raw = view.get("Config")
    require(isinstance(config_raw, dict), "candidate image inspect lacks config")
    config = cast(dict[str, Any], config_raw)
    require(config.get("Entrypoint") is ORIGINAL_ENTRYPOINT, "candidate image original entrypoint mismatch")
    require(config.get("Cmd") == ORIGINAL_CMD, "candidate image original command mismatch")
    labels = config.get("Labels") or {}
    require(isinstance(labels, dict), "candidate image labels are malformed")
    for key, expected in _expected_provenance_labels(identity).items():
        require(labels.get(key) == expected, f"candidate image provenance label mismatch: {key}")
    return {
        "image_sha256": identity.image_sha256,
        "source_sha": identity.source_sha,
        "source_tree_sha": identity.source_tree_sha,
    }


def validate_container_configuration(
    container_id: str,
    identity: CandidateIdentity,
    token: str,
) -> dict[str, Any]:
    """Bind an already-created gated container to the admitted image/source/tree."""

    validate_candidate_image(identity)
    view = _docker_inspect(container_id)
    config_raw = view.get("Config")
    host_config_raw = view.get("HostConfig")
    require(
        isinstance(config_raw, dict) and isinstance(host_config_raw, dict),
        "candidate inspect lacks Docker config",
    )
    config = cast(dict[str, Any], config_raw)
    host_config = cast(dict[str, Any], host_config_raw)
    require(view.get("Image") == identity.image_sha256, "candidate container image identity mismatch")
    require(config.get("Entrypoint") == GATE_ENTRYPOINT, "candidate gate entrypoint mismatch")
    require(config.get("Cmd") == gate_cmd(identity, token), "candidate gate command mismatch")
    restart = host_config.get("RestartPolicy")
    require(
        restart == {"Name": "no", "MaximumRetryCount": 0},
        "candidate must remain exact restart=no while gated",
    )

    labels = config.get("Labels") or {}
    require(isinstance(labels, dict), "candidate labels are malformed")
    for key, expected in _expected_provenance_labels(identity).items():
        require(labels.get(key) == expected, f"candidate provenance label mismatch: {key}")
    return {
        "container_id": str(view.get("Id", "")),
        "image_sha256": identity.image_sha256,
        "source_sha": identity.source_sha,
        "source_tree_sha": identity.source_tree_sha,
        "gate_path": identity.gate_path,
        "wrapper_sha256": wrapper_sha256(identity, token),
    }


def _sentinel_projection_script() -> str:
    return r"""
import hashlib,json,os,stat,sys
p=sys.argv[1]
flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
fd=os.open(p,flags)
try:
    s=os.fstat(fd)
    data=b''
    while True:
        block=os.read(fd,4096)
        if not block:
            break
        data+=block
finally:
    os.close(fd)
print(json.dumps({
    'regular':stat.S_ISREG(s.st_mode),
    'mode':stat.S_IMODE(s.st_mode),
    'uid':s.st_uid,
    'gid':s.st_gid,
    'size':s.st_size,
    'sha256':hashlib.sha256(data).hexdigest(),
},sort_keys=True))
"""


def sentinel_projection(container_id: str, identity: CandidateIdentity, token: str) -> dict[str, Any]:
    raw = _docker_exec(
        container_id,
        ["/opt/venv/bin/python", "-c", _sentinel_projection_script(), identity.gate_path],
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Failure("candidate gate sentinel projection is malformed") from exc
    require(isinstance(value, dict), "candidate gate sentinel projection is malformed")
    require(value.get("regular") is True, "candidate gate sentinel is not a regular file")
    require(value.get("mode") == GATE_MODE, "candidate gate sentinel mode mismatch")
    require(value.get("uid") == GATE_UID and value.get("gid") == GATE_GID, "candidate gate sentinel owner mismatch")
    expected = _token_bytes(token)
    require(value.get("size") == len(expected), "candidate gate sentinel size mismatch")
    require(value.get("sha256") == token_sha256(token), "candidate gate sentinel content mismatch")
    return cast(dict[str, Any], value)


def assert_absent(container_id: str, identity: CandidateIdentity) -> None:
    script = "import os,sys; raise SystemExit(1 if os.path.lexists(sys.argv[1]) else 0)"
    _docker_exec(container_id, ["/opt/venv/bin/python", "-c", script, identity.gate_path])


def _publication_temp_path(identity: CandidateIdentity, nonce: str) -> str:
    require(NONCE_RE.fullmatch(nonce) is not None, "candidate gate publication nonce is invalid")
    return identity.gate_path + ".tmp." + nonce


def _publish_sentinel(container_id: str, identity: CandidateIdentity, token: str, nonce: str) -> dict[str, Any]:
    expected = _token_bytes(token)
    temp_path = _publication_temp_path(identity, nonce)
    script = r"""
import os,sys
p=sys.argv[1]
directory=sys.argv[2]
tmp=sys.argv[3]
expected=bytes.fromhex(sys.argv[4])
flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)
fd=os.open(tmp,flags,0o600)
try:
    view=memoryview(expected)
    while view:
        written=os.write(fd,view)
        if written<=0:
            raise RuntimeError('short gate write')
        view=view[written:]
    os.fsync(fd)
finally:
    os.close(fd)
try:
    os.link(tmp,p,follow_symlinks=False)
    dfd=os.open(directory,os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
dfd=os.open(directory,os.O_RDONLY)
try:
    os.fsync(dfd)
finally:
    os.close(dfd)
"""
    _docker_exec(
        container_id,
        [
            "/opt/venv/bin/python",
            "-c",
            script,
            identity.gate_path,
            GATE_DIR,
            temp_path,
            expected.hex(),
        ],
    )
    return sentinel_projection(container_id, identity, token)


def _wait_exact_app_pid1(
    container_id: str,
    identity: CandidateIdentity,
    token: str,
    *,
    pre_publish_pid1: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    validate_gate_pid1(pre_publish_pid1, identity, token)
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        current = pid1_projection(container_id)
        last = current
        require(
            current["starttime"] == pre_publish_pid1.get("starttime")
            and current["netns_inode"] == pre_publish_pid1.get("netns_inode"),
            "candidate PID1 restarted while releasing gate",
        )
        if current.get("argv") == APP_PID1_ARGV:
            return validate_app_pid1(current)
        require(
            current.get("argv") == ["/bin/sh", *gate_cmd(identity, token)],
            "candidate PID1 is neither gate nor app while releasing gate",
        )
        time.sleep(0.05)
    raise Failure(f"candidate app exec was not proven after gate publication: {last}")


def publish(
    container_id: str,
    identity: CandidateIdentity,
    token: str,
    nonce: str,
    *,
    pre_publish_pid1: dict[str, Any],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Atomically publish the sentinel and prove same-epoch PID1 exec, or fail ambiguous."""

    validate_gate_pid1(pre_publish_pid1, identity, token)
    try:
        sentinel = _publish_sentinel(container_id, identity, token, nonce)
    except Failure:
        return reconcile_publish_attempt(
            container_id,
            identity,
            token,
            nonce,
            pre_publish_pid1=pre_publish_pid1,
            timeout_seconds=timeout_seconds,
        )
    try:
        pid1 = _wait_exact_app_pid1(
            container_id,
            identity,
            token,
            pre_publish_pid1=pre_publish_pid1,
            timeout_seconds=timeout_seconds,
        )
        _fsync_gate_dir(container_id)
    except Failure as exc:
        raise AmbiguousGateRelease(
            "candidate gate sentinel was published but same-process app release was not authoritatively proven"
        ) from exc
    return {
        "state": "published",
        "pid1": pid1,
        "sentinel_present": True,
        "sentinel": sentinel,
    }


def _path_projection(container_id: str, path: str) -> dict[str, Any]:
    script = r"""
import hashlib,json,os,stat,sys
p=sys.argv[1]
if not os.path.lexists(p):
    print(json.dumps({'exists':False},sort_keys=True))
    raise SystemExit(0)
flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
try:
    fd=os.open(p,flags)
except OSError:
    print(json.dumps({'exists':True,'openable':False},sort_keys=True))
    raise SystemExit(0)
try:
    s=os.fstat(fd)
    data=b''
    while True:
        block=os.read(fd,4096)
        if not block:
            break
        data+=block
finally:
    os.close(fd)
print(json.dumps({
    'exists':True,'openable':True,'regular':stat.S_ISREG(s.st_mode),
    'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,
    'size':s.st_size,'sha256':hashlib.sha256(data).hexdigest(),
},sort_keys=True))
"""
    raw = _docker_exec(container_id, ["/opt/venv/bin/python", "-c", script, path])
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Failure("candidate gate path projection is malformed") from exc
    require(
        isinstance(value, dict) and type(value.get("exists")) is bool,
        "candidate gate path projection is malformed",
    )
    return cast(dict[str, Any], value)


def _validate_owned_projection(value: dict[str, Any], token: str, *, label: str) -> None:
    expected = _token_bytes(token)
    require(value.get("exists") is True and value.get("openable") is True, f"candidate gate {label} is not openable")
    require(value.get("regular") is True, f"candidate gate {label} is not regular")
    require(value.get("mode") == GATE_MODE, f"candidate gate {label} mode mismatch")
    require(value.get("uid") == GATE_UID and value.get("gid") == GATE_GID, f"candidate gate {label} owner mismatch")
    require(value.get("size") == len(expected), f"candidate gate {label} size mismatch")
    require(value.get("sha256") == token_sha256(token), f"candidate gate {label} content mismatch")


def _fsync_gate_dir(container_id: str) -> None:
    script = "import os,sys; fd=os.open(sys.argv[1],os.O_RDONLY); os.fsync(fd); os.close(fd)"
    _docker_exec(container_id, ["/opt/venv/bin/python", "-c", script, GATE_DIR])


def _cleanup_exact_temp(container_id: str, identity: CandidateIdentity, token: str, nonce: str) -> None:
    path = _publication_temp_path(identity, nonce)
    projection = _path_projection(container_id, path)
    if projection.get("exists") is False:
        return
    _validate_owned_projection(projection, token, label="publication temp")
    script = r"""
import os,sys
os.unlink(sys.argv[1])
fd=os.open(sys.argv[2],os.O_RDONLY)
os.fsync(fd)
os.close(fd)
"""
    _docker_exec(container_id, ["/opt/venv/bin/python", "-c", script, path, GATE_DIR])


def reconcile_publish_attempt(
    container_id: str,
    identity: CandidateIdentity,
    token: str,
    nonce: str,
    *,
    pre_publish_pid1: dict[str, Any],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Classify an outcome-unknown publish without ever guessing rollback-safe."""

    _token_bytes(token)
    _publication_temp_path(identity, nonce)
    try:
        sentinel = _path_projection(container_id, identity.gate_path)
        if sentinel.get("exists") is False:
            raise AmbiguousGateRelease(
                "candidate gate publish was invoked but sentinel absence does not prove the publisher is terminal"
            )
        _validate_owned_projection(sentinel, token, label="sentinel")
        _fsync_gate_dir(container_id)
        _cleanup_exact_temp(container_id, identity, token, nonce)
        current = _wait_exact_app_pid1(
            container_id,
            identity,
            token,
            pre_publish_pid1=pre_publish_pid1,
            timeout_seconds=timeout_seconds,
        )
        _fsync_gate_dir(container_id)
        return {
            "state": "published_reconciled",
            "pid1": current,
            "sentinel_present": True,
            "sentinel": sentinel_projection(container_id, identity, token),
        }
    except AmbiguousGateRelease:
        raise
    except (Failure, OSError, KeyError, TypeError, ValueError) as exc:
        raise AmbiguousGateRelease("candidate gate publish outcome could not be reconciled") from exc


def remove_owned(container_id: str, identity: CandidateIdentity, token: str) -> None:
    """Remove an owned sentinel only before any publish attempt has occurred."""

    sentinel_projection(container_id, identity, token)
    script = r"""
import os,sys
os.unlink(sys.argv[1])
fd=os.open(sys.argv[2],os.O_RDONLY)
os.fsync(fd)
os.close(fd)
"""
    _docker_exec(container_id, ["/opt/venv/bin/python", "-c", script, identity.gate_path, GATE_DIR])


def _gate_mount_identity(view: dict[str, Any], *, label: str) -> tuple[str, str]:
    mounts_raw = view.get("Mounts")
    require(isinstance(mounts_raw, list), f"{label} inspect lacks mounts")
    mounts = cast(list[Any], mounts_raw)
    matches = [mount for mount in mounts if isinstance(mount, dict) and mount.get("Destination") == GATE_DIR]
    require(len(matches) == 1, f"{label} must have exactly one gate runtime mount")
    mount = cast(dict[str, Any], matches[0])
    mount_type_raw = mount.get("Type")
    require(
        isinstance(mount_type_raw, str) and mount_type_raw in {"volume", "bind"},
        f"{label} gate mount type is invalid",
    )
    mount_type = cast(str, mount_type_raw)
    if mount_type == "volume":
        locator_raw = mount.get("Name")
    else:
        locator_raw = mount.get("Source")
    require(isinstance(locator_raw, str) and bool(locator_raw), f"{label} gate mount identity is invalid")
    locator = cast(str, locator_raw)
    return mount_type, locator


def revoke_published_after_stop(
    candidate_container_id: str,
    view_container_id: str,
    identity: CandidateIdentity,
    token: str,
    nonce: str,
    *,
    expected_sentinel: dict[str, Any],
) -> dict[str, Any]:
    """Remove an authoritatively published sentinel after the candidate is stopped."""

    _token_bytes(token)
    validate_container_configuration(candidate_container_id, identity, token)
    candidate_view = _docker_inspect(candidate_container_id)
    state_raw = candidate_view.get("State")
    require(isinstance(state_raw, dict), "candidate inspect lacks stopped runtime state")
    state = cast(dict[str, Any], state_raw)
    require(
        state.get("Running") is False and state.get("Restarting") is False and state.get("Pid") == 0,
        "candidate must be authoritatively stopped before gate revocation",
    )
    view = _docker_inspect(view_container_id)
    view_state_raw = view.get("State")
    require(isinstance(view_state_raw, dict), "gate view inspect lacks runtime state")
    view_state = cast(dict[str, Any], view_state_raw)
    require(view_state.get("Running") is True, "gate view container must be running for revocation")
    require(
        _gate_mount_identity(candidate_view, label="candidate") == _gate_mount_identity(view, label="gate view"),
        "gate revocation view does not share the candidate runtime mount",
    )
    temp_path = _publication_temp_path(identity, nonce)
    current = sentinel_projection(view_container_id, identity, token)
    require(current == expected_sentinel, "candidate gate sentinel changed before rollback revocation")
    require(
        _path_projection(view_container_id, temp_path).get("exists") is False,
        "candidate gate publication temp remains before rollback revocation",
    )
    assert_no_sibling_gate_files(view_container_id, identity)
    script = r"""
import os,stat,sys
p=sys.argv[1]
directory=sys.argv[2]
expected=bytes.fromhex(sys.argv[3])
flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
fd=os.open(p,flags)
try:
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode): raise RuntimeError('gate is not regular')
    if stat.S_IMODE(s.st_mode)!=0o600 or s.st_uid!=1000 or s.st_gid!=1000:
        raise RuntimeError('gate metadata mismatch')
    data=b''
    while True:
        block=os.read(fd,4096)
        if not block: break
        data+=block
    if data!=expected: raise RuntimeError('gate content mismatch')
    by_name=os.lstat(p)
    if by_name.st_dev!=s.st_dev or by_name.st_ino!=s.st_ino:
        raise RuntimeError('gate pathname identity changed')
    os.unlink(p)
finally:
    os.close(fd)
dfd=os.open(directory,os.O_RDONLY)
os.fsync(dfd)
os.close(dfd)
if os.path.lexists(p): raise RuntimeError('gate still exists after unlink')
"""
    _docker_exec(
        view_container_id,
        ["/opt/venv/bin/python", "-c", script, identity.gate_path, GATE_DIR, _token_bytes(token).hex()],
    )
    assert_absent(view_container_id, identity)
    require(
        _path_projection(view_container_id, temp_path).get("exists") is False,
        "candidate gate publication temp appeared during rollback revocation",
    )
    assert_no_sibling_gate_files(view_container_id, identity)
    return {"removed": True, "prior": current}


def pid1_projection(container_id: str) -> dict[str, Any]:
    script = r"""
import json,os
raw=open('/proc/1/cmdline','rb').read()
argv=[item.decode('utf-8','strict') for item in raw.split(b'\0') if item]
fields=open('/proc/1/stat',encoding='utf-8').read().split()
print(json.dumps({
    'argv':argv,
    'starttime':fields[21],
    'netns_inode':os.stat('/proc/1/ns/net').st_ino,
},sort_keys=True))
"""
    raw = _docker_exec(container_id, ["/opt/venv/bin/python", "-c", script])
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Failure("candidate gate PID1 projection is malformed") from exc
    require(
        isinstance(value, dict)
        and isinstance(value.get("argv"), list)
        and all(isinstance(item, str) for item in value["argv"])
        and isinstance(value.get("starttime"), str)
        and value["starttime"].isdigit()
        and isinstance(value.get("netns_inode"), int)
        and value["netns_inode"] > 0,
        "candidate gate PID1 projection is malformed",
    )
    return cast(dict[str, Any], value)


def validate_gate_pid1(value: dict[str, Any], identity: CandidateIdentity, token: str) -> dict[str, Any]:
    require(value.get("argv") == ["/bin/sh", *gate_cmd(identity, token)], "candidate gate PID1 command mismatch")
    return value


def validate_app_pid1(value: dict[str, Any]) -> dict[str, Any]:
    require(value.get("argv") == APP_PID1_ARGV, "candidate app PID1 command mismatch")
    return value


def validate_entrypoint_bytes(container_id: str) -> None:
    output = _docker_exec(container_id, ["sha256sum", ORIGINAL_ENTRYPOINT_PATH]).strip().split()
    require(
        len(output) >= 1 and output[0] == ORIGINAL_ENTRYPOINT_SHA256,
        "candidate image entrypoint bytes changed",
    )


def assert_no_sibling_gate_files(container_id: str, identity: CandidateIdentity) -> None:
    script = r"""
from pathlib import Path
import sys
root=Path(sys.argv[1])
prefix=sys.argv[2]
expected=sys.argv[3]
siblings=sorted(p.name for p in root.glob(prefix+'*') if p.name != expected)
if siblings:
    raise SystemExit(1)
"""
    _docker_exec(
        container_id,
        ["/opt/venv/bin/python", "-c", script, GATE_DIR, GATE_PREFIX, identity.gate_name],
    )


def operation_projection(identity: CandidateIdentity, token: str, nonce: str) -> dict[str, str]:
    """Stable, non-secret values the cutover evidence should freeze before create."""

    _publication_temp_path(identity, nonce)
    return {
        "image_sha256": identity.image_sha256,
        "source_sha": identity.source_sha,
        "source_tree_sha": identity.source_tree_sha,
        "gate_path": identity.gate_path,
        "token_sha256": token_sha256(token),
        "wrapper_sha256": wrapper_sha256(identity, token),
        "entrypoint_sha256": ORIGINAL_ENTRYPOINT_SHA256,
    }
