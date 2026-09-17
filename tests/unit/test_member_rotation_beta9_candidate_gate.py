from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from scripts import member_rotation_beta9_candidate_gate as gate

pytestmark = pytest.mark.unit


def _identity() -> gate.CandidateIdentity:
    return gate.CandidateIdentity.admitted(
        image_sha256="a" * 64,
        source_sha="b" * 40,
        source_tree_sha="c" * 40,
    )


def _token() -> str:
    return "d" * 64


def _nonce() -> str:
    return "e" * 32


def _inspect(identity: gate.CandidateIdentity, token: str) -> dict:
    return {
        "Id": "f" * 64,
        "Image": identity.image_sha256,
        "Config": {
            "Entrypoint": gate.GATE_ENTRYPOINT,
            "Cmd": gate.gate_cmd(identity, token),
            "Labels": {
                "org.opencontainers.image.version": gate.PACKAGE_VERSION,
                "org.opencontainers.image.revision": identity.source_sha,
                "codex-lb.source-tree": identity.source_tree_sha,
                "codex-lb.upstream-source": gate.UPSTREAM_SOURCE_SHA,
                "codex-lb.q2-live-source": gate.Q2_LIVE_SOURCE_SHA,
            },
        },
        "HostConfig": {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        "State": {"Running": False, "Restarting": False, "Pid": 0},
        "Mounts": [
            {
                "Type": "volume",
                "Name": "beta9-gate-runtime",
                "Source": "/var/lib/docker/volumes/beta9-gate-runtime/_data",
                "Destination": gate.GATE_DIR,
            }
        ],
    }


def _image_inspect(identity: gate.CandidateIdentity) -> dict:
    return {
        "Id": identity.image_sha256,
        "Config": {
            "Entrypoint": gate.ORIGINAL_ENTRYPOINT,
            "Cmd": gate.ORIGINAL_CMD,
            "Labels": {
                "org.opencontainers.image.version": gate.PACKAGE_VERSION,
                "org.opencontainers.image.revision": identity.source_sha,
                "codex-lb.source-tree": identity.source_tree_sha,
                "codex-lb.upstream-source": gate.UPSTREAM_SOURCE_SHA,
                "codex-lb.q2-live-source": gate.Q2_LIVE_SOURCE_SHA,
            },
        },
    }


def test_identity_uses_full_image_digest_and_new_namespace() -> None:
    identity = _identity()
    assert identity.image_sha256 == "sha256:" + "a" * 64
    assert identity.gate_name == gate.GATE_PREFIX + "a" * 64 + gate.GATE_SUFFIX
    assert identity.gate_path == gate.GATE_DIR + "/" + identity.gate_name
    assert ".q2-beta-start-gate-592ace38-v1" not in identity.gate_path

    with pytest.raises(gate.Failure, match="image SHA"):
        gate.CandidateIdentity.admitted(image_sha256="short", source_sha="b" * 40, source_tree_sha="c" * 40)
    with pytest.raises(gate.Failure, match="source SHA"):
        gate.CandidateIdentity.admitted(image_sha256="a" * 64, source_sha="short", source_tree_sha="c" * 40)
    with pytest.raises(gate.Failure, match="source tree SHA"):
        gate.CandidateIdentity.admitted(image_sha256="a" * 64, source_sha="b" * 40, source_tree_sha="short")


def test_wrapper_is_restart_safe_and_execs_original_entrypoint() -> None:
    identity = _identity()
    script = gate.wrapper_script(identity, _token())
    assert identity.gate_path in script or "base64.b64decode" in script
    assert "then rc=0; else rc=$?; fi" in script
    assert "trap 'exit 143' TERM" in script
    assert f"exec {gate.ORIGINAL_ENTRYPOINT_PATH}" in script
    assert gate.gate_cmd(identity, _token()) == ["-ceu", script, gate.GATE_ARGV0]
    assert gate.wrapper_sha256(identity, _token()) == hashlib.sha256(script.encode()).hexdigest()


def test_operation_projection_contains_only_non_secret_gate_identity() -> None:
    identity = _identity()
    projection = gate.operation_projection(identity, _token(), _nonce())
    assert projection["image_sha256"] == identity.image_sha256
    assert projection["source_sha"] == identity.source_sha
    assert projection["source_tree_sha"] == identity.source_tree_sha
    assert projection["gate_path"] == identity.gate_path
    assert projection["token_sha256"] == gate.token_sha256(_token())
    assert _token() not in json.dumps(projection)


def test_validate_container_configuration_binds_image_source_tree_and_restart(monkeypatch) -> None:
    identity = _identity()
    view = _inspect(identity, _token())
    monkeypatch.setattr(gate, "_docker_inspect", lambda _container_id: view)
    monkeypatch.setattr(gate, "_docker_image_inspect", lambda _image: _image_inspect(identity))

    projection = gate.validate_container_configuration("candidate", identity, _token())
    assert projection["container_id"] == "f" * 64
    assert projection["gate_path"] == identity.gate_path

    for mutate, message in (
        (lambda v: v.update(Image="sha256:" + "1" * 64), "image identity"),
        (lambda v: v["Config"]["Labels"].update({"org.opencontainers.image.revision": "1" * 40}), "revision"),
        (lambda v: v["Config"]["Labels"].update({"codex-lb.source-tree": "1" * 40}), "source-tree"),
        (lambda v: v["HostConfig"]["RestartPolicy"].update(Name="unless-stopped"), "restart=no"),
        (lambda v: v["HostConfig"]["RestartPolicy"].update(MaximumRetryCount=1), "restart=no"),
    ):
        broken = _inspect(identity, _token())
        mutate(broken)
        monkeypatch.setattr(gate, "_docker_inspect", lambda _container_id, broken=broken: broken)
        with pytest.raises(gate.Failure, match=message):
            gate.validate_container_configuration("candidate", identity, _token())


def test_validate_candidate_image_rejects_mutable_provenance_substitution(monkeypatch) -> None:
    identity = _identity()
    image = _image_inspect(identity)
    monkeypatch.setattr(gate, "_docker_image_inspect", lambda _image: image)
    assert gate.validate_candidate_image(identity)["source_sha"] == identity.source_sha

    broken_label = _image_inspect(identity)
    broken_label["Config"]["Labels"]["codex-lb.source-tree"] = "1" * 40
    monkeypatch.setattr(gate, "_docker_image_inspect", lambda _image: broken_label)
    with pytest.raises(gate.Failure, match="image provenance label mismatch: codex-lb.source-tree"):
        gate.validate_candidate_image(identity)

    broken_cmd = _image_inspect(identity)
    broken_cmd["Config"]["Cmd"] = ["/bin/false"]
    monkeypatch.setattr(gate, "_docker_image_inspect", lambda _image: broken_cmd)
    with pytest.raises(gate.Failure, match="original command"):
        gate.validate_candidate_image(identity)


def test_publish_sentinel_uses_atomic_no_overwrite_sequence(monkeypatch) -> None:
    identity = _identity()
    commands: list[list[str]] = []
    projection = {
        "regular": True,
        "mode": gate.GATE_MODE,
        "uid": gate.GATE_UID,
        "gid": gate.GATE_GID,
        "size": len((_token() + "\n").encode()),
        "sha256": gate.token_sha256(_token()),
    }

    def fake_exec(_container: str, command: list[str], *, input_text=None) -> str:
        del input_text
        commands.append(command)
        return ""

    monkeypatch.setattr(gate, "_docker_exec", fake_exec)
    monkeypatch.setattr(gate, "sentinel_projection", lambda *_args: projection)
    result = gate._publish_sentinel("candidate", identity, _token(), _nonce())
    script = " ".join(commands[0])
    assert "O_EXCL" in script
    assert "O_NOFOLLOW" in script
    assert "os.link" in script
    assert "os.fsync" in script
    assert identity.gate_path in commands[0]
    assert result == projection


def test_publish_requires_same_pid1_epoch_through_normal_release(monkeypatch) -> None:
    identity = _identity()
    pre = {"argv": ["/bin/sh", *gate.gate_cmd(identity, _token())], "starttime": "123", "netns_inode": 9}
    app = {"argv": gate.APP_PID1_ARGV, "starttime": "123", "netns_inode": 9}
    sentinel = {"sha256": gate.token_sha256(_token())}
    calls: list[str] = []
    monkeypatch.setattr(gate, "_publish_sentinel", lambda *_args: sentinel)
    monkeypatch.setattr(gate, "pid1_projection", lambda *_args: app)
    monkeypatch.setattr(gate, "_fsync_gate_dir", lambda *_args: calls.append("fsync"))
    result = gate.publish(
        "candidate",
        identity,
        _token(),
        _nonce(),
        pre_publish_pid1=pre,
    )
    assert result == {"state": "published", "pid1": app, "sentinel_present": True, "sentinel": sentinel}
    assert calls == ["fsync"]

    changed_netns = {**app, "netns_inode": 10}
    monkeypatch.setattr(gate, "pid1_projection", lambda *_args: changed_netns)
    with pytest.raises(gate.AmbiguousGateRelease, match="sentinel was published"):
        gate.publish(
            "candidate",
            identity,
            _token(),
            _nonce(),
            pre_publish_pid1=pre,
        )


def test_reconcile_absent_is_always_ambiguous_after_publish_attempt(monkeypatch) -> None:
    identity = _identity()
    pre = {"argv": ["/bin/sh", *gate.gate_cmd(identity, _token())], "starttime": "123", "netns_inode": 9}
    monkeypatch.setattr(gate, "_path_projection", lambda *_args: {"exists": False})
    with pytest.raises(gate.AmbiguousGateRelease, match="does not prove"):
        gate.reconcile_publish_attempt(
            "candidate",
            identity,
            _token(),
            _nonce(),
            pre_publish_pid1=pre,
        )


def test_reconcile_present_but_unopenable_is_ambiguous(monkeypatch) -> None:
    identity = _identity()
    pre = {"argv": ["/bin/sh", *gate.gate_cmd(identity, _token())], "starttime": "123", "netns_inode": 9}
    monkeypatch.setattr(gate, "_path_projection", lambda *_args: {"exists": True, "openable": False})
    with pytest.raises(gate.AmbiguousGateRelease, match="could not be reconciled"):
        gate.reconcile_publish_attempt(
            "candidate",
            identity,
            _token(),
            _nonce(),
            pre_publish_pid1=pre,
        )


def test_reconcile_present_requires_same_pid1_epoch(monkeypatch) -> None:
    identity = _identity()
    pre = {"argv": ["/bin/sh", *gate.gate_cmd(identity, _token())], "starttime": "123", "netns_inode": 9}
    app = {"argv": gate.APP_PID1_ARGV, "starttime": "123", "netns_inode": 9}
    sentinel = {
        "exists": True,
        "openable": True,
        "regular": True,
        "mode": gate.GATE_MODE,
        "uid": gate.GATE_UID,
        "gid": gate.GATE_GID,
        "size": len((_token() + "\n").encode()),
        "sha256": gate.token_sha256(_token()),
    }
    calls: list[str] = []
    monkeypatch.setattr(gate, "_path_projection", lambda *_args: sentinel)
    monkeypatch.setattr(gate, "_fsync_gate_dir", lambda *_args: calls.append("fsync"))
    monkeypatch.setattr(gate, "_cleanup_exact_temp", lambda *_args: calls.append("cleanup"))
    monkeypatch.setattr(gate, "pid1_projection", lambda *_args: app)
    monkeypatch.setattr(gate, "sentinel_projection", lambda *_args: {"sha256": gate.token_sha256(_token())})

    result = gate.reconcile_publish_attempt(
        "candidate",
        identity,
        _token(),
        _nonce(),
        pre_publish_pid1=pre,
    )
    assert result["state"] == "published_reconciled"
    assert calls == ["fsync", "cleanup", "fsync"]

    restarted = {**app, "starttime": "124"}
    monkeypatch.setattr(gate, "pid1_projection", lambda *_args: restarted)
    with pytest.raises(gate.AmbiguousGateRelease):
        gate.reconcile_publish_attempt(
            "candidate",
            identity,
            _token(),
            _nonce(),
            pre_publish_pid1=pre,
        )


def test_revoke_published_after_stop_rechecks_exact_sentinel(monkeypatch) -> None:
    identity = _identity()
    projection = {
        "regular": True,
        "mode": gate.GATE_MODE,
        "uid": gate.GATE_UID,
        "gid": gate.GATE_GID,
        "size": len((_token() + "\n").encode()),
        "sha256": gate.token_sha256(_token()),
    }
    commands: list[list[str]] = []
    checks: list[str] = []
    monkeypatch.setattr(gate, "sentinel_projection", lambda *_args: projection)
    monkeypatch.setattr(gate, "_path_projection", lambda *_args: {"exists": False})
    monkeypatch.setattr(gate, "assert_absent", lambda *_args: checks.append("absent"))
    monkeypatch.setattr(gate, "assert_no_sibling_gate_files", lambda *_args: checks.append("siblings"))
    monkeypatch.setattr(gate, "_docker_image_inspect", lambda _image: _image_inspect(identity))
    candidate = _inspect(identity, _token())
    view = _inspect(identity, _token())
    view["Id"] = "9" * 64
    view["State"] = {"Running": True, "Restarting": False, "Pid": 456}
    monkeypatch.setattr(gate, "_docker_inspect", lambda container: candidate if container == "candidate" else view)

    def fake_exec(_container: str, command: list[str], *, input_text=None) -> str:
        del input_text
        commands.append(command)
        return ""

    monkeypatch.setattr(gate, "_docker_exec", fake_exec)
    result = gate.revoke_published_after_stop(
        "candidate",
        "stable-view",
        identity,
        _token(),
        _nonce(),
        expected_sentinel=projection,
    )
    script = " ".join(commands[0])
    assert "O_NOFOLLOW" in script
    assert "os.lstat" in script
    assert "os.unlink" in script
    assert result == {"removed": True, "prior": projection}
    assert checks == ["siblings", "absent", "siblings"]

    running = _inspect(identity, _token())
    running["State"] = {"Running": True, "Restarting": False, "Pid": 123}
    monkeypatch.setattr(gate, "_docker_inspect", lambda container: running if container == "candidate" else view)
    with pytest.raises(gate.Failure, match="authoritatively stopped"):
        gate.revoke_published_after_stop(
            "candidate",
            "stable-view",
            identity,
            _token(),
            _nonce(),
            expected_sentinel=projection,
        )

    mismatched_view = _inspect(identity, _token())
    mismatched_view["State"] = {"Running": True, "Restarting": False, "Pid": 456}
    mismatched_view["Mounts"][0]["Name"] = "different-runtime"
    monkeypatch.setattr(
        gate, "_docker_inspect", lambda container: candidate if container == "candidate" else mismatched_view
    )
    with pytest.raises(gate.Failure, match="does not share"):
        gate.revoke_published_after_stop(
            "candidate",
            "stable-view",
            identity,
            _token(),
            _nonce(),
            expected_sentinel=projection,
        )


def test_pid1_and_entrypoint_contracts(monkeypatch) -> None:
    identity = _identity()
    shell = {"argv": ["/bin/sh", *gate.gate_cmd(identity, _token())], "starttime": "123", "netns_inode": 99}
    app = {"argv": gate.APP_PID1_ARGV, "starttime": "123", "netns_inode": 99}
    assert gate.validate_gate_pid1(shell, identity, _token()) == shell
    assert gate.validate_app_pid1(app) == app
    with pytest.raises(gate.Failure, match="app PID1"):
        gate.validate_app_pid1(shell)

    monkeypatch.setattr(
        gate,
        "_docker_exec",
        lambda *_args, **_kwargs: gate.ORIGINAL_ENTRYPOINT_SHA256 + "  /app/scripts/docker-entrypoint.sh\n",
    )
    gate.validate_entrypoint_bytes("candidate")
    monkeypatch.setattr(
        gate, "_docker_exec", lambda *_args, **_kwargs: "0" * 64 + "  /app/scripts/docker-entrypoint.sh\n"
    )
    with pytest.raises(gate.Failure, match="entrypoint bytes changed"):
        gate.validate_entrypoint_bytes("candidate")


def test_owned_projection_rejects_wrong_mode_and_owner() -> None:
    good = {
        "exists": True,
        "openable": True,
        "regular": True,
        "mode": gate.GATE_MODE,
        "uid": gate.GATE_UID,
        "gid": gate.GATE_GID,
        "size": len((_token() + "\n").encode()),
        "sha256": gate.token_sha256(_token()),
    }
    wrong_mode = {**good, "mode": 0o644}
    with pytest.raises(gate.Failure, match="mode mismatch"):
        gate._validate_owned_projection(wrong_mode, _token(), label="sentinel")
    wrong_owner = {**good, "uid": gate.GATE_UID + 1}
    with pytest.raises(gate.Failure, match="owner mismatch"):
        gate._validate_owned_projection(wrong_owner, _token(), label="sentinel")


def test_run_with_nonzero_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "secret detail"),
    )
    with pytest.raises(gate.Failure, match="command failed"):
        gate._run(["docker", "exec"])
