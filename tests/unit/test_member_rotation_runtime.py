from __future__ import annotations

import base64
import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.db.models import MemberRotationQuotaOperation
from app.modules.member_switch.rotation_controller import RotationController
from app.modules.member_switch.runtime_attestation import (
    FileRuntimeAttestation,
    HostRuntimeObservation,
    SignedHostObservation,
    observation_bytes,
)
from app.modules.member_switch.schemas import (
    CANARY_TELEMETRY_BINARY_SHA256,
    CANARY_TELEMETRY_SOURCE_SHA256,
    CANARY_TELEMETRY_VERSION,
    P4_TYPED_TELEMETRY_CONTRACT,
    P4_TYPED_TELEMETRY_OPS_COMMIT,
    CompanionTypedTelemetryProvenance,
)
from tests.unit.test_member_rotation_controller import (
    NOW,
    OUTGOING,
    admitted_quota,
    evidence,
    p4_provenance,
    receipt,
)
from tests.unit.test_member_rotation_controller import (
    rotation_context as rotation_context,
)

pytestmark = pytest.mark.unit
ENDPOINT = "http://127.0.0.1:53418/member-switch/v1/account-pool"


def write_observation(directory, **changes):
    values = dict(
        endpoint=ENDPOINT,
        provenance=p4_provenance(),
        pid=123,
        process_started="synthetic-start",
        executable_device=1,
        executable_inode=2,
        observed_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    values.update(changes)
    observation = HostRuntimeObservation.model_validate(values)
    private = Ed25519PrivateKey.generate()
    (directory / "host-verifier.pub").write_bytes(private.public_key().public_bytes_raw())
    signed = SignedHostObservation(
        observation=observation,
        signature=base64.b64encode(private.sign(observation_bytes(observation))).decode(),
    )
    (directory / "host-observation.json").write_text(signed.model_dump_json())
    return signed


@pytest.mark.parametrize(
    "failure", ["missing", "expired", "future", "long_ttl", "endpoint", "release", "key", "tamper", "oversized"]
)
def test_host_evidence_fails_closed(tmp_path, failure):
    changes = {}
    if failure == "expired":
        changes = {"observed_at": NOW - timedelta(seconds=30), "expires_at": NOW}
    elif failure == "future":
        changes = {"observed_at": NOW + timedelta(seconds=1)}
    elif failure == "long_ttl":
        changes = {"expires_at": NOW + timedelta(seconds=31)}
    elif failure == "endpoint":
        changes = {"endpoint": ENDPOINT.replace("127.0.0.1", "localhost")}
    elif failure == "release":
        changes = {"provenance": p4_provenance(version="2.11.48-canary.1")}
    signed = write_observation(tmp_path, **changes)
    if failure == "missing":
        (tmp_path / "host-observation.json").unlink()
    elif failure == "key":
        (tmp_path / "host-verifier.pub").write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
    elif failure == "tamper":
        signed.observation = signed.observation.model_copy(update={"pid": 999})
        (tmp_path / "host-observation.json").write_text(signed.model_dump_json())
    elif failure == "oversized":
        (tmp_path / "host-observation.json").write_bytes(b" " * 16385)
    with pytest.raises(ValueError, match="rotation_runtime_attestation_invalid"):
        FileRuntimeAttestation(tmp_path, ENDPOINT, clock=lambda: NOW).require(p4_provenance())


def test_observation_is_reread_and_not_cached(tmp_path):
    write_observation(tmp_path)
    verifier = FileRuntimeAttestation(tmp_path, ENDPOINT, clock=lambda: NOW)
    assert verifier.require(p4_provenance()).pid == 123
    (tmp_path / "host-observation.json").unlink()
    with pytest.raises(ValueError):
        verifier.require(p4_provenance())


@pytest.mark.parametrize("failure", ["unconfigured", "expires_during_quota", "revoked_during_admission"])
async def test_runtime_gate_at_real_controller_dispatch(rotation_context, tmp_path, monkeypatch, failure):
    _, switch, controls, companion, sessions, clock = rotation_context
    write_observation(tmp_path)
    verifier = None if failure == "unconfigured" else FileRuntimeAttestation(tmp_path, ENDPOINT, clock=clock)
    controller = RotationController(controls, switch, sessions, sessions, clock=clock, runtime_attestation=verifier)
    _, weekly, reset = evidence("runtime-gate")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-runtime")
    if failure == "expires_during_quota":
        original = controller._quota_request

        async def expire(*args):
            await original(*args)
            clock.current += timedelta(seconds=30)

        monkeypatch.setattr(controller, "_quota_request", expire)
    elif failure == "revoked_during_admission":
        original_admission = companion.admission

        async def revoke():
            (tmp_path / "host-observation.json").unlink(missing_ok=True)
            return await original_admission()

        monkeypatch.setattr(companion, "admission", revoke)
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-runtime",
        p4_provenance=p4_provenance(),
    )
    assert state.phase == "needs_attention"
    assert companion.start_calls == 0
    async with sessions() as session:
        row = await session.get(MemberRotationQuotaOperation, quota.operation_id)
        assert row is not None and row.remove_effect == "authoritative_non_effect"
        assert row.reservation_released_at is not None
    await controller.resume(state.id)
    assert companion.start_calls == 0


def canary_provenance(**changes):
    values = dict(
        version=CANARY_TELEMETRY_VERSION,
        contract=P4_TYPED_TELEMETRY_CONTRACT,
        binary_sha256=CANARY_TELEMETRY_BINARY_SHA256,
        source_manifest_sha256=CANARY_TELEMETRY_SOURCE_SHA256,
    )
    values.update(changes)
    return CompanionTypedTelemetryProvenance.model_validate(values)


def test_legacy_signature_bytes_remain_compatible(tmp_path):
    signed = write_observation(tmp_path)
    legacy = signed.observation.model_dump(mode="json")
    del legacy["provenance"]["source_manifest_sha256"]
    raw = json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    assert observation_bytes(signed.observation) == raw
    key = Ed25519PrivateKey.generate()
    (tmp_path / "host-verifier.pub").write_bytes(key.public_key().public_bytes_raw())
    payload = {"observation": legacy, "signature": base64.b64encode(key.sign(raw)).decode()}
    (tmp_path / "host-observation.json").write_text(json.dumps(payload))
    assert FileRuntimeAttestation(tmp_path, ENDPOINT, clock=lambda: NOW).require(p4_provenance()).pid == 123
    assert not p4_provenance().model_copy(update={"source_manifest_sha256": CANARY_TELEMETRY_SOURCE_SHA256}).qualified


def test_canary_source_identity_is_cryptographically_bound(tmp_path):
    expected = canary_provenance()
    signed = write_observation(tmp_path, provenance=expected)
    verifier = FileRuntimeAttestation(tmp_path, ENDPOINT, clock=lambda: NOW)
    assert verifier.require(expected).provenance == expected
    altered = canary_provenance(source_manifest_sha256="0" * 64)
    signed.observation = signed.observation.model_copy(update={"provenance": altered})
    (tmp_path / "host-observation.json").write_text(signed.model_dump_json())
    with pytest.raises(ValueError, match="rotation_runtime_attestation_invalid"):
        verifier.require(expected)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"source_manifest_sha256": None},
        {"source_manifest_sha256": "0" * 64},
        {"binary_sha256": "0" * 64},
        {"version": "2.11.48-canary.2"},
        {"contract": "unqualified"},
        {"ops_commit": P4_TYPED_TELEMETRY_OPS_COMMIT},
    ],
)
async def test_current_artifact_dispatch_and_restart(rotation_context, tmp_path, changes):
    _, switch, controls, companion, sessions, clock = rotation_context
    provenance = canary_provenance(**changes)
    write_observation(tmp_path, provenance=provenance)
    verifier = FileRuntimeAttestation(tmp_path, ENDPOINT, clock=clock)
    controller = RotationController(controls, switch, sessions, sessions, clock=clock, runtime_attestation=verifier)
    _, weekly, reset = evidence("current-artifact")
    quota = await admitted_quota(sessions, clock, weekly, reset, operation_id="quota-current-artifact")
    state = await controller.evaluate_and_start(
        weekly=weekly,
        reset=reset,
        quota=quota,
        current_member=OUTGOING,
        final_usage_receipt=receipt(),
        membership_epoch="epoch-current-artifact",
        p4_provenance=provenance,
    )
    if changes:
        assert not provenance.qualified
        assert state.phase == "needs_attention"
        assert companion.start_calls == 0
        with pytest.raises(ValueError, match="rotation_runtime_attestation_invalid"):
            verifier.require(provenance)
    else:
        assert provenance.qualified
        assert companion.start_calls == 1
        assert state.phase != "needs_attention"
    restarted = RotationController(controls, switch, sessions, sessions, clock=clock, runtime_attestation=verifier)
    await restarted.resume(state.id)
    assert companion.start_calls == (0 if changes else 1)
