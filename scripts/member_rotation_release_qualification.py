#!/usr/bin/env python3
"""Non-destructive qualification helpers for usage-driven member rotation.

The module deliberately has no effect-bearing client. It validates evidence that
other, already-existing build/runtime tools collect and exposes small protocols
for the G2 controller adapter. Nothing here can redeem a reset credit, mutate a
Business membership, perform OAuth, install the Companion, or deploy a lane.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, cast

G1_SHA = "ce807515439a285147c807f2a83b1f221cb67626"

P4_OWNING_OPS_COMMIT = "47ac829a23b9811537bcd2d21ae9b8003c9c464a"
P4_RECONSTRUCTION_BASELINE = "97becd4b66a5569efd3895d10ff7c9beec3eea97"
P4_VERSION = "2.11.47"
P4_BINARY_SHA256 = "0f7b665e47f1b2cd4959814afe3ee68fe0aa5cc25a264e295997d3499290f1ce"
P4_PATCH_SHA256 = "eb8cb39de01e2b92c834f16bab571e8e3c1420d507113a146dd47da674e9f9fc"
P4_PATCH_UNCOMPRESSED_SHA256 = "b4a4dca639f63870bd6800835905b8c5a68a5c54dc83d3a4d410e651bc7a48da"
P4_REPLAY_TOUCHED_TREE_SHA256 = "1feb8130c6d683569d8dd5d6f4e0a3a5f705afa6e66b53dc2e9e26eb614ed76d"
PRODUCTION_OFFICIAL_ALEMBIC_HEAD = "20260913_000000_add_oidc_provider_flow"
PREDECESSOR_OFFICIAL_ALEMBIC_HEAD = "20260910_000000_request_logs_missing_cost_index"
MEMBER_ROTATION_EXTENSION_CONTRACT = "member_rotation_local_extension_v1"
P4_CONTRACT = frozenset(
    {
        "typed_remove_response_observation",
        "typed_invite_response_observation",
        "recursive_bounded_sanitization",
        "effect_boundary_no_replay",
    }
)

EffectKind = Literal["reset_consume", "remove", "invite"]
_ALL_EFFECT_COUNTERS = ("reset_consume", "remove", "invite", "join", "oauth")
CanaryEffect = Literal["remove", "invite"]

FAILURE_BOUNDARY_CASES = (
    "unknown_weekly",
    "stale_weekly",
    "reset_required",
    "reset_pending",
    "reset_unavailable",
    "reset_recovered",
    "quota_blocked",
    "invalid_evidence",
    "owner_member_mismatch",
    "p4_capability_unavailable",
    "p4_provenance_unavailable",
)

CONCURRENCY_CASES = (
    "duplicate_scheduler_tick",
    "two_replicas_same_workspace",
    "manual_flow_active",
    "automatic_flow_active",
    "companion_restart",
    "backend_restart",
    "db_transaction_interruption",
    "claim_lease_expiry",
)

P4_TYPED_VALUE_CASES = ("number", "boolean", "string", "explicit_null", "absent")
P4_CAPTURE_CASES = ("empty_body", "parse_failed", "response_not_received", "transport_failure")

ROLLBACK_STATE_KEYS = (
    "quota_history",
    "unknown_effect_receipts",
    "removed_member_snapshots",
    "reset_resolution_state",
    "oauth_member_records",
)
ROLLBACK_EXTENSION_TABLES = (
    "member_switch_control_records",
    "member_switch_command_receipts",
    "member_rotation_quota_operations",
    "member_rotation_workspace_controls",
    "workspace_member_usage_reset_invalidations",
    "workspace_member_final_usage_snapshots",
)
LEGACY_DASHBOARD_CREDENTIAL_COLUMNS = (
    "password_hash",
    "totp_secret_encrypted",
    "totp_last_verified_step",
)

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class QualificationError(RuntimeError):
    """A fail-closed qualification result."""


@dataclass(frozen=True, slots=True)
class ExternalEffects:
    reset_consume: int = 0
    remove: int = 0
    invite: int = 0
    join: int = 0
    oauth: int = 0

    def count(self, effect: EffectKind) -> int:
        return cast(int, getattr(self, effect))


@dataclass(frozen=True, slots=True)
class GateDecision:
    authorized: bool
    code: str


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    before: ExternalEffects
    after: ExternalEffects
    observation_id: str


@dataclass(frozen=True, slots=True)
class DurableEffectReceipt:
    """Identity of the durable effect receipt that survives process reconstruction."""

    operation_id: str
    effect: EffectKind
    receipt_id: str


@dataclass(frozen=True, slots=True)
class TelemetryObservation:
    operation: Literal["remove", "invite"]
    case: str
    capture_state: str
    value_present: bool = False
    value: object | None = None
    sensitive_values_retained: bool = False


class RestartNoReplayAdapter(Protocol):
    """G2 adapter seam for one deliberately lost effect response."""

    async def cross_effect_boundary_and_lose_response(self, effect: EffectKind) -> None: ...

    def restart(self) -> RestartNoReplayAdapter: ...

    async def reconcile_read_only(
        self,
        effect: EffectKind,
        receipt: DurableEffectReceipt,
    ) -> DurableEffectReceipt: ...

    def effects(self) -> ExternalEffects: ...

    def durable_effect_receipt(self, effect: EffectKind) -> DurableEffectReceipt | None: ...


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _timestamp(value: object, label: str) -> datetime:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(cast(str, value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualificationError(f"{label} is not an ISO-8601 timestamp") from exc
    _require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _extension_table_fingerprints(value: object, label: str) -> dict[str, tuple[int, str]]:
    tables = _mapping(value, label)
    _require(
        set(tables) == set(ROLLBACK_EXTENSION_TABLES),
        f"{label} must contain exactly the six local extension tables",
    )
    result: dict[str, tuple[int, str]] = {}
    for table_name in ROLLBACK_EXTENSION_TABLES:
        evidence = _mapping(tables.get(table_name), f"{label}.{table_name}")
        count = evidence.get("count")
        _require(type(count) is int and count >= 0, f"{label}.{table_name}.count is invalid")
        result[table_name] = (
            cast(int, count),
            _normalized_sha256(evidence.get("sha256"), f"{label}.{table_name}.sha256"),
        )
    return result


def _verify_post_migration_predecessor_boundary_probe(
    probe: Mapping[str, Any],
    *,
    label: str,
    expected_image_sha256: str,
    expected_source_sha: str,
    expected_role: str,
    database_container_id: str,
    database_container_started_at: str,
    system_identifier: str,
    postgres_snapshot_fingerprint: str,
    extension_schema_sha256: str,
) -> None:
    """Require read-only proof that a beta.7 predecessor rejects the beta.9 DB epoch."""

    _require(probe.get("probe_kind") == "migration_state", f"{label} boundary probe kind is invalid")
    _require(probe.get("compatible") is False, f"{label} unexpectedly accepts the beta.9 database")
    _require(
        _normalized_sha256(probe.get("image_sha256"), f"{label} boundary probe image") == expected_image_sha256,
        f"{label} boundary probe image mismatch",
    )
    _require(
        _require_git_sha(probe.get("source_sha"), f"{label} boundary probe source") == expected_source_sha
        and probe.get("role") == expected_role,
        f"{label} boundary probe release identity mismatch",
    )
    _require(
        _normalized_sha256(probe.get("database_container_id"), f"{label} boundary probe database container")
        == database_container_id
        and probe.get("database_container_started_at") == database_container_started_at
        and probe.get("system_identifier") == system_identifier,
        f"{label} boundary probe is not bound to the admitted beta.9 database identity",
    )
    _require(
        probe.get("current_revision") == PRODUCTION_OFFICIAL_ALEMBIC_HEAD
        and probe.get("head_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD
        and probe.get("needs_upgrade") is True
        and probe.get("is_ahead") is True
        and probe.get("unknown_revisions") == [PRODUCTION_OFFICIAL_ALEMBIC_HEAD],
        f"{label} did not prove the non-rolling beta.9 migration boundary",
    )
    _require(
        _normalized_sha256(probe.get("postgres_snapshot_fingerprint"), f"{label} boundary probe snapshot")
        == postgres_snapshot_fingerprint
        and _normalized_sha256(probe.get("extension_schema_sha256"), f"{label} boundary probe extension schema")
        == extension_schema_sha256,
        f"{label} boundary probe is not bound to the admitted beta.9 database state",
    )


def _verify_predecessor_runtime_start_probe(
    probe: Mapping[str, Any],
    *,
    label: str,
    expected_image_sha256: str,
    expected_source_sha: str,
    expected_role: str,
    database_container_id: str,
    database_container_started_at: str,
    system_identifier: str,
    postgres_snapshot_fingerprint: str,
    extension_schema_sha256: str,
) -> None:
    """Require an exact predecessor to start and become ready on the restored beta.7 DB epoch."""

    _require(probe.get("probe_kind") == "runtime_start", f"{label} rollback probe kind is invalid")
    _require(probe.get("compatible") is True, f"{label} rollback DB compatibility was not verified")
    _require(
        _normalized_sha256(probe.get("image_sha256"), f"rollback {label} probe image") == expected_image_sha256,
        f"{label} rollback start probe image mismatch",
    )
    _require(
        _require_git_sha(probe.get("source_sha"), f"rollback {label} probe source") == expected_source_sha
        and probe.get("role") == expected_role,
        f"{label} rollback start probe release identity mismatch",
    )
    _normalized_sha256(probe.get("container_id"), f"rollback {label} probe container")
    container_started_at = probe.get("container_started_at")
    _require(
        isinstance(container_started_at, str) and bool(container_started_at.strip()),
        f"{label} rollback start probe container start identity missing",
    )
    _require(
        _timestamp(container_started_at, f"rollback {label} probe container_started_at")
        > _timestamp(database_container_started_at, f"rollback {label} probe database_container_started_at"),
        f"{label} rollback predecessor was not started after the restored database epoch",
    )
    _require(
        probe.get("running") is True
        and probe.get("ready") is True
        and probe.get("readiness_path") == "/health/ready"
        and type(probe.get("readiness_status")) is int
        and probe.get("readiness_status") == 200
        and type(probe.get("restart_count")) is int
        and probe.get("restart_count") == 0
        and probe.get("migrate_on_startup") is False,
        f"{label} rollback predecessor did not prove a clean ready startup",
    )
    _require(
        probe.get("system_identifier") == system_identifier
        and _normalized_sha256(probe.get("database_container_id"), f"rollback {label} probe database container")
        == database_container_id
        and probe.get("database_container_started_at") == database_container_started_at
        and probe.get("current_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD
        and probe.get("head_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        f"{label} rollback start probe database identity mismatch",
    )
    _require(
        probe.get("needs_upgrade") is False and probe.get("is_ahead") is False and probe.get("unknown_revisions") == [],
        f"{label} rollback migration state is not compatible",
    )
    _require(
        _normalized_sha256(probe.get("extension_schema_sha256"), f"rollback {label} probe extension schema")
        == extension_schema_sha256,
        f"{label} rollback extension schema mismatch",
    )
    _require(
        _normalized_sha256(probe.get("postgres_snapshot_fingerprint"), f"rollback {label} probe snapshot")
        == postgres_snapshot_fingerprint,
        f"{label} rollback probe is not bound to the restored pre-migration snapshot",
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _normalized_sha256(value: object, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be a SHA-256 string")
    text = cast(str, value)
    normalized = text.removeprefix("sha256:").casefold()
    _require(bool(_SHA256_RE.fullmatch(normalized)), f"{label} is not a SHA-256 digest")
    return normalized


def _require_git_sha(value: object, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be a git SHA")
    normalized = cast(str, value).casefold()
    _require(bool(_SHA40_RE.fullmatch(normalized)), f"{label} is not a full git SHA")
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _sha256_gzip_payload(path: Path) -> str:
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _patch_paths(payload: bytes) -> tuple[Path, ...]:
    paths: list[Path] = []
    for raw_line in payload.splitlines():
        line = raw_line.decode("utf-8", errors="strict")
        match = re.fullmatch(r"diff -ru a/(.+) b/(.+)", line)
        if match is None:
            continue
        before, after = match.groups()
        _require(before == after, f"P4 patch renames are not allowed in replay tooling: {before} -> {after}")
        relative = Path(before)
        _require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe P4 patch path: {before}")
        paths.append(relative)
    _require(bool(paths), "P4 patch does not contain any replayable file paths")
    return tuple(dict.fromkeys(paths))


def replay_p4_patch(*, artifact: Path, base_source: Path, scratch_root: Path) -> dict[str, str | int]:
    """Apply P4 to a private touched-file copy and return a deterministic replay digest."""

    _require(artifact.is_file(), f"P4 artifact is missing: {artifact}")
    _require(base_source.is_dir(), f"P4 replay base source is missing: {base_source}")
    _require(scratch_root.is_dir(), f"P4 replay scratch root is missing: {scratch_root}")
    with gzip.open(artifact, "rb") as handle:
        payload = handle.read()
    paths = _patch_paths(payload)

    with tempfile.TemporaryDirectory(prefix="p7-p4-replay-", dir=scratch_root) as temporary:
        replay_root = Path(temporary) / "source"
        replay_root.mkdir()
        for relative in paths:
            source = base_source / relative
            _require(source.is_file(), f"P4 replay base file is missing: {relative}")
            target = replay_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        result = subprocess.run(
            ["patch", "-p1", "-d", str(replay_root)],
            input=payload,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _require(
            result.returncode == 0,
            "P4 patch replay failed: " + result.stderr.decode("utf-8", errors="replace").strip(),
        )

        digest = hashlib.sha256()
        for relative in sorted(paths, key=lambda item: item.as_posix()):
            target = replay_root / relative
            _require(target.is_file(), f"P4 replay output is missing: {relative}")
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(target.read_bytes())
            digest.update(b"\0")

    replay_digest = digest.hexdigest()
    _require(replay_digest == P4_REPLAY_TOUCHED_TREE_SHA256, "P4 replay touched-tree SHA mismatch")
    return {
        "replay_touched_files": len(paths),
        "replay_touched_tree_sha256": replay_digest,
    }


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise QualificationError(f"git {' '.join(args)} failed for {root}")
    return result.stdout.strip()


def require_zero_effects(before: ExternalEffects, after: ExternalEffects, *, label: str) -> None:
    _require(after == before, f"{label}: external effect count changed: before={before!r} after={after!r}")


def qualify_effect_gate(
    *,
    feature_enabled: bool,
    foundation_admission_ready: bool,
    p4_capability_verified: bool,
    p4_provenance_verified: bool,
    conflicting_operation: bool = False,
) -> GateDecision:
    """Return the final qualification gate decision without performing an effect."""

    if not feature_enabled:
        return GateDecision(False, "feature_off")
    if not foundation_admission_ready:
        return GateDecision(False, "foundation_not_ready")
    if not p4_capability_verified:
        return GateDecision(False, "p4_capability_unavailable")
    if not p4_provenance_verified:
        return GateDecision(False, "p4_provenance_unavailable")
    if conflicting_operation:
        return GateDecision(False, "operation_conflict")
    return GateDecision(True, "qualified")


def qualify_scenario_matrix(
    results: Mapping[str, ScenarioResult],
    *,
    required: Sequence[str],
) -> None:
    missing = sorted(set(required) - set(results))
    _require(not missing, "qualification matrix is missing scenarios: " + ", ".join(missing))
    observation_ids: set[str] = set()
    for scenario in required:
        result = results[scenario]
        _require(bool(result.observation_id.strip()), f"{scenario}: observation identity is missing")
        _require(
            result.observation_id not in observation_ids,
            f"{scenario}: observation identity was reused across scenarios",
        )
        observation_ids.add(result.observation_id)
        require_zero_effects(result.before, result.after, label=scenario)


async def qualify_restart_no_replay(adapter: RestartNoReplayAdapter, effect: EffectKind) -> None:
    """Cross exactly one effect, reconstruct, and prove reconciliation is read-only."""

    before = adapter.effects()
    _require(adapter.durable_effect_receipt(effect) is None, f"{effect}: fixture already has durable effect evidence")
    await adapter.cross_effect_boundary_and_lose_response(effect)
    crossed = adapter.effects()
    _require(
        crossed.count(effect) == before.count(effect) + 1,
        f"{effect}: fixture did not cross exactly one effect boundary",
    )
    for other in _ALL_EFFECT_COUNTERS:
        if other != effect:
            _require(
                getattr(crossed, other) == getattr(before, other),
                f"{effect}: crossing unexpectedly emitted {other}",
            )

    crossed_receipt = adapter.durable_effect_receipt(effect)
    _require(crossed_receipt is not None, f"{effect}: effect boundary did not persist a durable receipt")
    assert crossed_receipt is not None
    _require(crossed_receipt.effect == effect, f"{effect}: durable receipt effect identity mismatch")
    _require(bool(crossed_receipt.operation_id.strip()), f"{effect}: durable receipt operation identity is missing")
    _require(bool(crossed_receipt.receipt_id.strip()), f"{effect}: durable receipt identity is missing")

    restarted = adapter.restart()
    _require(restarted.effects() == crossed, f"{effect}: restart lost durable effect evidence")
    _require(
        restarted.durable_effect_receipt(effect) == crossed_receipt,
        f"{effect}: restart did not reconstruct the same durable effect receipt",
    )
    reconciled_receipt = await restarted.reconcile_read_only(effect, crossed_receipt)
    _require(restarted.effects() == crossed, f"{effect}: reconciliation replayed an external effect")
    _require(
        reconciled_receipt == crossed_receipt,
        f"{effect}: reconciliation did not authoritatively read the same durable receipt",
    )


def qualify_p4_telemetry_matrix(observations: Sequence[TelemetryObservation]) -> None:
    """Validate the normalized P4 fixture matrix for both mutation boundaries."""

    by_key = {(item.operation, item.case): item for item in observations}
    expected = {
        (operation, case)
        for operation in ("remove", "invite")
        for case in (*P4_TYPED_VALUE_CASES, *P4_CAPTURE_CASES, "sensitive_nested_dynamic")
    }
    missing = sorted(expected - set(by_key))
    _require(not missing, f"P4 telemetry matrix is missing cases: {missing}")

    for operation in ("remove", "invite"):
        number = by_key[(operation, "number")]
        boolean = by_key[(operation, "boolean")]
        string = by_key[(operation, "string")]
        explicit_null = by_key[(operation, "explicit_null")]
        absent = by_key[(operation, "absent")]

        _require(number.capture_state == "parsed", f"{operation}: number was not parsed")
        _require(
            number.value_present and type(number.value) in {int, float},
            f"{operation}: JSON number type was not retained",
        )
        _require(boolean.capture_state == "parsed", f"{operation}: boolean was not parsed")
        _require(
            boolean.value_present and type(boolean.value) is bool,
            f"{operation}: JSON boolean type was not retained",
        )
        _require(string.capture_state == "parsed", f"{operation}: string was not parsed")
        _require(
            string.value_present and isinstance(string.value, str) and bool(string.value),
            f"{operation}: safe string type was not retained",
        )
        _require(
            explicit_null.capture_state == "parsed" and explicit_null.value_present and explicit_null.value is None,
            f"{operation}: explicit JSON null was not retained distinctly",
        )
        _require(
            absent.capture_state == "parsed" and not absent.value_present,
            f"{operation}: absent field was not retained distinctly",
        )

        for capture_case in P4_CAPTURE_CASES:
            observation = by_key[(operation, capture_case)]
            _require(
                observation.capture_state == capture_case and not observation.value_present,
                f"{operation}: {capture_case} was not retained as an explicit capture state",
            )

        sensitive = by_key[(operation, "sensitive_nested_dynamic")]
        _require(
            not sensitive.sensitive_values_retained,
            f"{operation}: sensitive nested/dynamic telemetry was retained",
        )


def qualify_retention_before_remove(events: Sequence[str]) -> None:
    """Require durable outgoing Usage retention to precede remove authority."""

    _require(events.count("final_usage_retained") == 1, "qualification needs exactly one final Usage retention event")
    _require(events.count("remove_authority_committed") == 1, "qualification needs exactly one remove authority event")
    retained = events.index("final_usage_retained")
    remove_authority = events.index("remove_authority_committed")
    _require(retained < remove_authority, "remove authority was committed before final Usage retention")


def verify_p4_artifact(
    *,
    artifact: Path,
    manifest: Path,
    ops_worktree: Path,
) -> dict[str, str]:
    """Verify the frozen P4 patch and distinguish artifact ownership from source baseline."""

    _require(
        P4_OWNING_OPS_COMMIT != P4_RECONSTRUCTION_BASELINE,
        "P4 artifact ownership and reconstruction baseline must remain distinct provenance axes",
    )
    _require(artifact.is_file(), f"P4 artifact is missing: {artifact}")
    _require(manifest.is_file(), f"P4 manifest is missing: {manifest}")
    _require(ops_worktree.is_dir(), f"P4 ops worktree is missing: {ops_worktree}")
    resolved_ops = ops_worktree.resolve()
    _require(artifact.resolve().is_relative_to(resolved_ops), "P4 artifact is outside the owning ops worktree")
    _require(manifest.resolve().is_relative_to(resolved_ops), "P4 manifest is outside the owning ops worktree")
    data = _load_json(manifest)
    frozen = _mapping(data.get("frozen"), "P4 frozen provenance")
    candidate = _mapping(data.get("candidate"), "P4 candidate")
    qualification = _mapping(data.get("qualification"), "P4 qualification")

    _require(
        frozen.get("ops_commit") == P4_RECONSTRUCTION_BASELINE,
        "P4 reconstructed-source baseline does not match the frozen artifact",
    )
    _require(candidate.get("version") == P4_VERSION, "P4 candidate version mismatch")
    _require(
        _normalized_sha256(candidate.get("patch_sha256"), "P4 manifest patch SHA") == P4_PATCH_SHA256,
        "P4 manifest patch SHA mismatch",
    )
    _require(
        _normalized_sha256(candidate.get("patch_uncompressed_sha256"), "P4 manifest decompressed SHA")
        == P4_PATCH_UNCOMPRESSED_SHA256,
        "P4 manifest decompressed SHA mismatch",
    )
    _require(
        _normalized_sha256(candidate.get("local_binary_sha256"), "P4 candidate binary SHA") == P4_BINARY_SHA256,
        "P4 candidate binary SHA mismatch",
    )
    _require(candidate.get("deployed") is False, "P4 manifest unexpectedly marks the candidate deployed")
    _require(qualification.get("live_effects_used") is False, "P4 qualification unexpectedly used live effects")
    _require(qualification.get("patch_replay") == "exact", "P4 manifest does not record exact patch replay")
    dotnet = _mapping(qualification.get("dotnet"), "P4 .NET qualification")
    node_runtime = _mapping(qualification.get("node_runtime"), "P4 Node qualification")
    dotnet_passed = dotnet.get("passed")
    dotnet_failed = dotnet.get("failed")
    node_passed = node_runtime.get("passed")
    node_failed = node_runtime.get("failed")
    _require(
        type(dotnet_passed) is int and dotnet_passed >= 559 and dotnet_failed == 0,
        "P4 .NET qualification is incomplete",
    )
    _require(
        type(node_passed) is int and node_passed >= 76 and node_failed == 0,
        "P4 Node qualification is incomplete",
    )

    contract = data.get("p4_contract")
    _require(isinstance(contract, list), "P4 contract list is missing")
    contract_items = cast(list[Any], contract)
    _require(
        P4_CONTRACT.issubset({str(item) for item in contract_items}),
        "P4 required contract capability is missing",
    )

    compressed = _sha256_file(artifact)
    uncompressed = _sha256_gzip_payload(artifact)
    _require(compressed == P4_PATCH_SHA256, "P4 artifact gzip SHA mismatch")
    _require(uncompressed == P4_PATCH_UNCOMPRESSED_SHA256, "P4 artifact decompressed SHA mismatch")

    owning_commit = _git(ops_worktree, "rev-parse", "HEAD")
    _require(owning_commit == P4_OWNING_OPS_COMMIT, "P4 artifact-owning ops commit mismatch")
    _require(not _git(ops_worktree, "status", "--porcelain"), "P4 artifact-owning ops worktree is not clean")

    return {
        "artifact_sha256": compressed,
        "artifact_uncompressed_sha256": uncompressed,
        "candidate_version": P4_VERSION,
        "candidate_binary_sha256": P4_BINARY_SHA256,
        "artifact_owning_ops_commit": owning_commit,
        "reconstructed_source_baseline": P4_RECONSTRUCTION_BASELINE,
    }


def verify_source_candidate(root: Path, *, expected_source_sha: str, expected_package_version: str) -> None:
    expected = _require_git_sha(expected_source_sha, "expected source SHA")
    _require(root.is_dir(), f"candidate source root is missing: {root}")
    _require(_git(root, "rev-parse", "HEAD") == expected, "candidate source HEAD mismatch")
    _require(not _git(root, "status", "--porcelain"), "candidate source worktree is not clean")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = _mapping(project.get("project"), "pyproject project").get("version")
    _require(version == expected_package_version, "candidate package version mismatch")


def _parse_effects(value: object, label: str) -> ExternalEffects:
    data = _mapping(value, label)
    values: dict[str, int] = {}
    for field in ("reset_consume", "remove", "invite", "join", "oauth"):
        raw = data.get(field)
        _require(type(raw) is int and raw >= 0, f"{label}.{field} must be a non-negative integer")
        values[field] = cast(int, raw)
    return ExternalEffects(**values)


def verify_preflight(
    evidence: Mapping[str, Any],
    *,
    expected_source_sha: str,
    expected_package_version: str,
    expected_image_sha256: str,
    expected_workspace_account_id: str,
    expected_stable_sha256: str,
    expected_beta_sha256: str,
    expected_postgres_container_id: str,
    expected_postgres_system_identifier: str,
    expected_rollback_stable_sha256: str,
    expected_rollback_beta_sha256: str,
    expected_rollback_stable_source_sha: str,
    expected_rollback_beta_source_sha: str,
    expected_rollback_stable_role: str,
    expected_rollback_beta_role: str,
) -> dict[str, str]:
    """Validate read-only final-G2 preflight evidence collected by existing ops tooling."""

    _require(evidence.get("schema_version") == 1, "unsupported preflight schema")
    subject = _mapping(evidence.get("subject"), "subject")
    candidate = _mapping(evidence.get("candidate"), "candidate")
    p4 = _mapping(evidence.get("p4"), "p4")
    postgres = _mapping(evidence.get("postgres"), "postgres")
    migration = _mapping(evidence.get("migration"), "migration")
    operations = _mapping(evidence.get("operations"), "operations")
    runtime = _mapping(evidence.get("runtime"), "runtime")
    feature = _mapping(evidence.get("feature"), "feature")
    rollback = _mapping(evidence.get("rollback"), "rollback")

    _require(bool(expected_workspace_account_id.strip()), "expected workspace account identity is missing")
    _require(
        subject.get("workspace_account_id") == expected_workspace_account_id,
        "preflight workspace account identity mismatch",
    )

    source_sha = _require_git_sha(candidate.get("source_sha"), "candidate.source_sha")
    _require(
        source_sha == _require_git_sha(expected_source_sha, "expected source SHA"),
        "candidate source SHA mismatch",
    )
    _require(candidate.get("package_version") == expected_package_version, "candidate package version mismatch")
    image_sha = _normalized_sha256(candidate.get("image_sha256"), "candidate.image_sha256")
    _require(
        image_sha == _normalized_sha256(expected_image_sha256, "expected image SHA"),
        "candidate image SHA mismatch",
    )
    _require(candidate.get("provenance_verified") is True, "candidate provenance was not verified")

    _require(p4.get("version") == P4_VERSION, "preflight P4 version mismatch")
    _require(
        _normalized_sha256(p4.get("binary_sha256"), "p4.binary_sha256") == P4_BINARY_SHA256,
        "preflight P4 binary SHA mismatch",
    )
    _require(
        _normalized_sha256(p4.get("patch_sha256"), "p4.patch_sha256") == P4_PATCH_SHA256,
        "preflight P4 artifact SHA mismatch",
    )
    _require(
        _normalized_sha256(p4.get("patch_uncompressed_sha256"), "p4.patch_uncompressed_sha256")
        == P4_PATCH_UNCOMPRESSED_SHA256,
        "preflight P4 decompressed artifact SHA mismatch",
    )
    _require(p4.get("artifact_owning_ops_commit") == P4_OWNING_OPS_COMMIT, "preflight P4 owning commit mismatch")
    _require(
        p4.get("reconstructed_source_baseline") == P4_RECONSTRUCTION_BASELINE,
        "preflight P4 source baseline mismatch",
    )
    _require(p4.get("capability_verified") is True, "preflight P4 capability is unavailable")
    _require(p4.get("provenance_verified") is True, "preflight P4 provenance is unavailable")
    p4_contract = p4.get("contract")
    _require(isinstance(p4_contract, list), "preflight P4 contract evidence is missing")
    _require(
        P4_CONTRACT.issubset({str(item) for item in cast(list[Any], p4_contract)}),
        "preflight P4 contract evidence is incomplete",
    )

    _require(postgres.get("gate") == "PASS", "PostgreSQL gate did not pass")
    postgres_container_id = _normalized_sha256(postgres.get("container_id"), "postgres.container_id")
    _require(
        postgres_container_id == _normalized_sha256(expected_postgres_container_id, "expected PostgreSQL container id"),
        "PostgreSQL container identity mismatch",
    )
    raw_postgres_started_at = postgres.get("container_started_at")
    _require(
        isinstance(raw_postgres_started_at, str) and bool(raw_postgres_started_at.strip()),
        "PostgreSQL start identity missing",
    )
    postgres_started_at = cast(str, raw_postgres_started_at)
    raw_system_identifier = postgres.get("system_identifier")
    _require(
        isinstance(raw_system_identifier, str) and raw_system_identifier.isdigit(),
        "PostgreSQL system identifier is invalid",
    )
    system_identifier = cast(str, raw_system_identifier)
    _require(system_identifier == expected_postgres_system_identifier, "PostgreSQL system identifier mismatch")
    _require(
        postgres.get("current_revision") == PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
        "PostgreSQL current revision is not the official production head",
    )
    _require(
        postgres.get("official_head_revision") == PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
        "PostgreSQL official head identity mismatch",
    )
    _require(
        postgres.get("member_rotation_extension_contract") == MEMBER_ROTATION_EXTENSION_CONTRACT,
        "member-rotation extension contract identity mismatch",
    )
    _require(
        postgres.get("member_rotation_extension_gate") == "PASS",
        "member-rotation extension PostgreSQL gate did not pass",
    )
    postgres_snapshot = _normalized_sha256(
        postgres.get("snapshot_fingerprint"),
        "postgres.snapshot_fingerprint",
    )
    extension_schema_sha = _normalized_sha256(
        postgres.get("extension_schema_sha256"),
        "postgres.extension_schema_sha256",
    )
    _require(migration.get("policy") == "PASS", "migration policy gate did not pass")
    _require(migration.get("schema_drift") == "PASS", "migration schema-drift gate did not pass")
    _require(
        migration.get("database_container_id") == postgres.get("container_id")
        and migration.get("database_container_started_at") == postgres_started_at
        and migration.get("system_identifier") == system_identifier,
        "migration evidence is not bound to the admitted PostgreSQL identity",
    )
    _require(
        migration.get("current_revision") == PRODUCTION_OFFICIAL_ALEMBIC_HEAD
        and migration.get("head_revision") == PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
        "migration evidence is not at the official production head",
    )
    _require(
        migration.get("candidate_head_revision") == PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
        "candidate Alembic head is not the official production head",
    )
    _require(
        migration.get("extension_schema_sha256") == postgres.get("extension_schema_sha256"),
        "migration evidence extension schema mismatch",
    )
    _require(
        migration.get("postgres_snapshot_fingerprint") == postgres.get("snapshot_fingerprint"),
        "migration evidence is not from the admitted PostgreSQL snapshot",
    )
    _require(
        type(operations.get("active_member_switch_controls")) is int
        and operations.get("active_member_switch_controls") == 0,
        "active member-switch control exists",
    )
    _require(
        type(operations.get("active_oauth_member_operations")) is int
        and operations.get("active_oauth_member_operations") == 0,
        "active OAuth/member operation exists",
    )
    _require(operations.get("oauth_device_slots") == 0, "active OAuth device-flow slot exists")
    _require(operations.get("automatic_rotation_enabled_rows") == 0, "automatic rotation intent is enabled")
    _require(
        operations.get("postgres_snapshot_fingerprint") == postgres.get("snapshot_fingerprint"),
        "operation evidence is not from the admitted PostgreSQL snapshot",
    )

    expected_stable = _normalized_sha256(expected_stable_sha256, "expected Stable SHA")
    expected_beta = _normalized_sha256(expected_beta_sha256, "expected Beta SHA")
    stable_before = _normalized_sha256(runtime.get("stable_before_sha256"), "runtime.stable_before_sha256")
    stable_after = _normalized_sha256(runtime.get("stable_after_sha256"), "runtime.stable_after_sha256")
    beta_before = _normalized_sha256(runtime.get("beta_before_sha256"), "runtime.beta_before_sha256")
    beta_after = _normalized_sha256(runtime.get("beta_after_sha256"), "runtime.beta_after_sha256")
    _require(stable_before == expected_stable, "Stable before identity mismatch")
    _require(stable_after == expected_stable, "Stable identity changed during read-only preflight")
    _require(beta_before == expected_beta, "Beta before identity mismatch")
    _require(beta_after == expected_beta, "Beta identity changed during read-only preflight")
    _require(
        runtime.get("postgres_snapshot_fingerprint") == postgres.get("snapshot_fingerprint"),
        "runtime evidence is not bound to the admitted PostgreSQL snapshot",
    )

    _require(feature.get("default_enabled") is False, "automatic rotation is not default OFF")
    _require(feature.get("enabled") is False, "automatic rotation is enabled during preflight")
    configuration_effects = _parse_effects(feature.get("configuration_effects"), "feature.configuration_effects")
    require_zero_effects(ExternalEffects(), configuration_effects, label="feature configuration")
    off_window_effects = _parse_effects(
        feature.get("automatic_effects_during_off_window"),
        "feature.automatic_effects_during_off_window",
    )
    require_zero_effects(ExternalEffects(), off_window_effects, label="feature OFF observation window")
    _require(
        feature.get("postgres_snapshot_fingerprint") == postgres.get("snapshot_fingerprint"),
        "feature evidence is not bound to the admitted PostgreSQL snapshot",
    )

    _require(rollback.get("exists") is True, "rollback artifact does not exist")
    rollback_identity = _normalized_sha256(rollback.get("identity_sha256"), "rollback.identity_sha256")
    _require(rollback.get("verified") is True, "rollback artifact existence/identity was not verified")
    _require(
        rollback.get("strategy") == "restore_pre_migration_database",
        "rollback strategy must restore the verified pre-migration database",
    )

    expected_rollback_stable = _normalized_sha256(expected_rollback_stable_sha256, "expected rollback Stable SHA")
    expected_rollback_beta = _normalized_sha256(expected_rollback_beta_sha256, "expected rollback Beta SHA")
    expected_rollback_stable_source = _require_git_sha(
        expected_rollback_stable_source_sha,
        "expected rollback Stable source SHA",
    )
    expected_rollback_beta_source = _require_git_sha(
        expected_rollback_beta_source_sha,
        "expected rollback Beta source SHA",
    )

    predecessor_boundary = _mapping(
        rollback.get("post_migration_predecessor_boundary"),
        "rollback.post_migration_predecessor_boundary",
    )
    _verify_post_migration_predecessor_boundary_probe(
        _mapping(predecessor_boundary.get("stable"), "rollback.post_migration_predecessor_boundary.stable"),
        label="Stable",
        expected_image_sha256=expected_rollback_stable,
        expected_source_sha=expected_rollback_stable_source,
        expected_role=expected_rollback_stable_role,
        database_container_id=postgres_container_id,
        database_container_started_at=postgres_started_at,
        system_identifier=system_identifier,
        postgres_snapshot_fingerprint=postgres_snapshot,
        extension_schema_sha256=extension_schema_sha,
    )
    _verify_post_migration_predecessor_boundary_probe(
        _mapping(predecessor_boundary.get("beta"), "rollback.post_migration_predecessor_boundary.beta"),
        label="Beta predecessor",
        expected_image_sha256=expected_rollback_beta,
        expected_source_sha=expected_rollback_beta_source,
        expected_role=expected_rollback_beta_role,
        database_container_id=postgres_container_id,
        database_container_started_at=postgres_started_at,
        system_identifier=system_identifier,
        postgres_snapshot_fingerprint=postgres_snapshot,
        extension_schema_sha256=extension_schema_sha,
    )

    rollback_source = _mapping(rollback.get("source_database"), "rollback.source_database")
    _require(
        rollback_source.get("current_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD
        and rollback_source.get("head_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "rollback source database is not at the predecessor official head",
    )
    _require(
        rollback_source.get("member_rotation_extension_preserved") is True,
        "rollback source does not preserve rotation extensions",
    )
    rollback_source_snapshot = _normalized_sha256(
        rollback_source.get("snapshot_fingerprint"),
        "rollback.source_database.snapshot_fingerprint",
    )
    rollback_source_extension = _normalized_sha256(
        rollback_source.get("extension_schema_sha256"),
        "rollback.source_database.extension_schema_sha256",
    )
    _require(
        rollback_source_extension == extension_schema_sha,
        "rollback source extension schema fingerprint mismatch",
    )
    _require(
        _normalized_sha256(
            rollback_source.get("backup_identity_sha256"),
            "rollback.source_database.backup_identity_sha256",
        )
        == rollback_identity,
        "rollback source database is not bound to the verified backup artifact",
    )
    rollback_source_extension_tables = _extension_table_fingerprints(
        rollback_source.get("extension_tables"),
        "rollback.source_database.extension_tables",
    )
    rollback_source_credential_columns = rollback_source.get("legacy_credential_columns")
    _require(
        isinstance(rollback_source_credential_columns, list)
        and len(rollback_source_credential_columns) == len(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS)
        and set(rollback_source_credential_columns) == set(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS),
        "rollback source legacy dashboard credential columns are incomplete",
    )
    rollback_source_credentials = _normalized_sha256(
        rollback_source.get("legacy_credential_fingerprint_sha256"),
        "rollback.source_database.legacy_credential_fingerprint_sha256",
    )
    _require(
        rollback_source.get("retired_sentinel_present") is False,
        "rollback source unexpectedly has the beta.9 retired-credential sentinel",
    )

    restore = _mapping(rollback.get("restore_rehearsal"), "rollback.restore_rehearsal")
    restore_container_id = _normalized_sha256(
        restore.get("database_container_id"),
        "rollback.restore_rehearsal.database_container_id",
    )
    restore_started_at = restore.get("database_container_started_at")
    _require(
        isinstance(restore_started_at, str) and bool(restore_started_at.strip()),
        "rollback restore database start identity missing",
    )
    restore_system_identifier = restore.get("system_identifier")
    _require(
        isinstance(restore_system_identifier, str) and restore_system_identifier.isdigit(),
        "rollback restore system identifier is invalid",
    )
    _require(
        restore.get("current_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD
        and restore.get("head_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "rollback restored database is not at the predecessor official head",
    )
    _require(
        restore.get("member_rotation_extension_preserved") is True,
        "rollback restore does not preserve rotation extensions",
    )
    _require(
        _normalized_sha256(
            restore.get("extension_schema_sha256"),
            "rollback.restore_rehearsal.extension_schema_sha256",
        )
        == rollback_source_extension,
        "rollback restore extension schema fingerprint mismatch",
    )
    _require(
        _extension_table_fingerprints(
            restore.get("extension_tables"),
            "rollback.restore_rehearsal.extension_tables",
        )
        == rollback_source_extension_tables,
        "rollback restore changed local extension table data fingerprints",
    )
    restore_credential_columns = restore.get("legacy_credential_columns")
    _require(
        isinstance(restore_credential_columns, list)
        and len(restore_credential_columns) == len(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS)
        and set(restore_credential_columns) == set(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS),
        "rollback restore legacy dashboard credential columns are incomplete",
    )
    _require(
        _normalized_sha256(
            restore.get("legacy_credential_fingerprint_sha256"),
            "rollback.restore_rehearsal.legacy_credential_fingerprint_sha256",
        )
        == rollback_source_credentials
        and restore.get("retired_sentinel_present") is False,
        "rollback restore did not recover the pre-migration dashboard credential state",
    )
    restore_snapshot = _normalized_sha256(
        restore.get("snapshot_fingerprint"),
        "rollback.restore_rehearsal.snapshot_fingerprint",
    )
    _require(
        restore_snapshot == rollback_source_snapshot
        and _normalized_sha256(
            restore.get("source_snapshot_fingerprint"),
            "rollback.restore_rehearsal.source_snapshot_fingerprint",
        )
        == rollback_source_snapshot,
        "rollback restore is not an exact pre-migration snapshot restore",
    )
    _require(
        _normalized_sha256(
            restore.get("backup_identity_sha256"),
            "rollback.restore_rehearsal.backup_identity_sha256",
        )
        == rollback_identity,
        "rollback restore is not bound to the verified backup artifact",
    )
    predecessor = _mapping(rollback.get("predecessor"), "rollback.predecessor")
    _require(
        _normalized_sha256(predecessor.get("stable_image_sha256"), "rollback.predecessor.stable_image_sha256")
        == expected_rollback_stable,
        "rollback Stable predecessor identity mismatch",
    )
    _require(
        _normalized_sha256(predecessor.get("beta_image_sha256"), "rollback.predecessor.beta_image_sha256")
        == expected_rollback_beta,
        "rollback Beta predecessor identity mismatch",
    )
    _require(
        _require_git_sha(predecessor.get("stable_source_sha"), "rollback.predecessor.stable_source_sha")
        == expected_rollback_stable_source
        and predecessor.get("stable_role") == expected_rollback_stable_role,
        "rollback Stable predecessor release identity mismatch",
    )
    _require(
        _require_git_sha(predecessor.get("beta_source_sha"), "rollback.predecessor.beta_source_sha")
        == expected_rollback_beta_source
        and predecessor.get("beta_role") == expected_rollback_beta_role,
        "rollback Beta predecessor release identity mismatch",
    )
    stable_probe = _mapping(rollback.get("stable_start_probe"), "rollback.stable_start_probe")
    beta_probe = _mapping(rollback.get("beta_start_probe"), "rollback.beta_start_probe")
    for label, probe, expected_image, expected_source, expected_role in (
        (
            "Stable",
            stable_probe,
            expected_rollback_stable,
            expected_rollback_stable_source,
            expected_rollback_stable_role,
        ),
        (
            "Beta predecessor",
            beta_probe,
            expected_rollback_beta,
            expected_rollback_beta_source,
            expected_rollback_beta_role,
        ),
    ):
        _verify_predecessor_runtime_start_probe(
            probe,
            label=label,
            expected_image_sha256=expected_image,
            expected_source_sha=expected_source,
            expected_role=expected_role,
            database_container_id=restore_container_id,
            database_container_started_at=cast(str, restore_started_at),
            system_identifier=cast(str, restore_system_identifier),
            postgres_snapshot_fingerprint=restore_snapshot,
            extension_schema_sha256=rollback_source_extension,
        )

    return {
        "workspace_account_id": expected_workspace_account_id,
        "source_sha": source_sha,
        "package_version": expected_package_version,
        "image_sha256": image_sha,
        "stable_sha256": stable_before,
        "beta_sha256": beta_before,
        "rollback_identity_sha256": rollback_identity,
        "rollback_source_snapshot_fingerprint": rollback_source_snapshot,
        "rollback_restore_container_id": restore_container_id,
        "rollback_predecessor_head_revision": PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "postgres_container_id": postgres_container_id,
        "postgres_system_identifier": system_identifier,
        "postgres_head_revision": PRODUCTION_OFFICIAL_ALEMBIC_HEAD,
        "postgres_snapshot_fingerprint": postgres_snapshot,
        "extension_schema_sha256": extension_schema_sha,
    }


def verify_rollback_state(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    expected_rollback_stable_sha256: str,
    expected_rollback_beta_sha256: str,
    expected_rollback_stable_source_sha: str,
    expected_rollback_beta_source_sha: str,
    expected_rollback_stable_role: str,
    expected_rollback_beta_role: str,
) -> None:
    """Require exact durable-state preservation across pre-migration DB restore rollback."""

    for key in ROLLBACK_STATE_KEYS:
        previous = _mapping(before.get(key), f"before.{key}")
        current = _mapping(after.get(key), f"after.{key}")
        previous_count = previous.get("count")
        current_count = current.get("count")
        _require(type(previous_count) is int and previous_count >= 0, f"before.{key}.count is invalid")
        _require(type(current_count) is int and current_count >= 0, f"after.{key}.count is invalid")
        previous_digest = _normalized_sha256(previous.get("sha256"), f"before.{key}.sha256")
        current_digest = _normalized_sha256(current.get("sha256"), f"after.{key}.sha256")
        _require(
            (current_count, current_digest) == (previous_count, previous_digest),
            f"rollback did not preserve {key}",
        )

    before_database = _mapping(before.get("database"), "before.database")
    after_database = _mapping(after.get("database"), "after.database")
    _require(
        before_database.get("current_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD
        and before_database.get("head_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "pre-migration rollback source is not at the predecessor official head",
    )
    _require(
        after_database.get("current_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD
        and after_database.get("head_revision") == PREDECESSOR_OFFICIAL_ALEMBIC_HEAD,
        "restored rollback database is not at the predecessor official head",
    )
    _require(
        before_database.get("extension_contract") == MEMBER_ROTATION_EXTENSION_CONTRACT
        and after_database.get("extension_contract") == MEMBER_ROTATION_EXTENSION_CONTRACT,
        "rollback member-rotation extension contract mismatch",
    )
    _require(
        _normalized_sha256(before_database.get("extension_schema_sha256"), "before.database.extension_schema_sha256")
        == _normalized_sha256(after_database.get("extension_schema_sha256"), "after.database.extension_schema_sha256"),
        "rollback extension schema fingerprint changed",
    )
    before_snapshot = _normalized_sha256(
        before_database.get("snapshot_fingerprint"), "before.database.snapshot_fingerprint"
    )
    _require(
        _normalized_sha256(after_database.get("snapshot_fingerprint"), "after.database.snapshot_fingerprint")
        == before_snapshot
        and _normalized_sha256(
            after_database.get("source_snapshot_fingerprint"),
            "after.database.source_snapshot_fingerprint",
        )
        == before_snapshot,
        "rollback database snapshot was not restored exactly",
    )
    before_credential_columns = before_database.get("legacy_credential_columns")
    after_credential_columns = after_database.get("legacy_credential_columns")
    _require(
        isinstance(before_credential_columns, list)
        and isinstance(after_credential_columns, list)
        and len(before_credential_columns) == len(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS)
        and len(after_credential_columns) == len(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS)
        and set(before_credential_columns) == set(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS)
        and set(after_credential_columns) == set(LEGACY_DASHBOARD_CREDENTIAL_COLUMNS),
        "rollback legacy dashboard credential columns were not restored",
    )
    _require(
        _normalized_sha256(
            before_database.get("legacy_credential_fingerprint_sha256"),
            "before.database.legacy_credential_fingerprint_sha256",
        )
        == _normalized_sha256(
            after_database.get("legacy_credential_fingerprint_sha256"),
            "after.database.legacy_credential_fingerprint_sha256",
        )
        and before_database.get("retired_sentinel_present") is False
        and after_database.get("retired_sentinel_present") is False,
        "rollback legacy dashboard credential state changed",
    )
    backup_identity = _normalized_sha256(
        before_database.get("backup_identity_sha256"),
        "before.database.backup_identity_sha256",
    )
    _require(
        _normalized_sha256(after_database.get("backup_identity_sha256"), "after.database.backup_identity_sha256")
        == backup_identity
        and after_database.get("restore_verified") is True,
        "rollback database restore is not bound to the verified backup",
    )
    restored_container_id = _normalized_sha256(
        after_database.get("container_id"),
        "after.database.container_id",
    )
    restored_started_at = after_database.get("container_started_at")
    restored_system_identifier = after_database.get("system_identifier")
    _require(
        isinstance(restored_started_at, str)
        and bool(restored_started_at.strip())
        and isinstance(restored_system_identifier, str)
        and restored_system_identifier.isdigit(),
        "restored rollback database identity is invalid",
    )
    before_extensions = _mapping(before.get("extension_tables"), "before.extension_tables")
    after_extensions = _mapping(after.get("extension_tables"), "after.extension_tables")
    for table_name in ROLLBACK_EXTENSION_TABLES:
        previous = _mapping(before_extensions.get(table_name), f"before.extension_tables.{table_name}")
        current = _mapping(after_extensions.get(table_name), f"after.extension_tables.{table_name}")
        previous_count = previous.get("count")
        current_count = current.get("count")
        _require(type(previous_count) is int and previous_count >= 0, f"before extension {table_name} count invalid")
        _require(type(current_count) is int and current_count >= 0, f"after extension {table_name} count invalid")
        _require(
            _normalized_sha256(previous.get("sha256"), f"before extension {table_name} sha256")
            == _normalized_sha256(current.get("sha256"), f"after extension {table_name} sha256")
            and previous_count == current_count,
            f"rollback did not preserve extension table {table_name}",
        )
    expected_stable_image = _normalized_sha256(expected_rollback_stable_sha256, "expected rollback Stable SHA")
    expected_beta_image = _normalized_sha256(expected_rollback_beta_sha256, "expected rollback Beta SHA")
    expected_stable_source = _require_git_sha(
        expected_rollback_stable_source_sha, "expected rollback Stable source SHA"
    )
    expected_beta_source = _require_git_sha(expected_rollback_beta_source_sha, "expected rollback Beta source SHA")

    predecessor = _mapping(after.get("predecessor"), "after.predecessor")
    _require(
        _normalized_sha256(predecessor.get("stable_image_sha256"), "after.predecessor.stable_image_sha256")
        == expected_stable_image
        and _require_git_sha(predecessor.get("stable_source_sha"), "after.predecessor.stable_source_sha")
        == expected_stable_source
        and predecessor.get("stable_role") == expected_rollback_stable_role,
        "rollback Stable predecessor release identity mismatch",
    )
    _require(
        _normalized_sha256(predecessor.get("beta_image_sha256"), "after.predecessor.beta_image_sha256")
        == expected_beta_image
        and _require_git_sha(predecessor.get("beta_source_sha"), "after.predecessor.beta_source_sha")
        == expected_beta_source
        and predecessor.get("beta_role") == expected_rollback_beta_role,
        "rollback Beta predecessor release identity mismatch",
    )

    restored_extension_schema = _normalized_sha256(
        after_database.get("extension_schema_sha256"),
        "after.database.extension_schema_sha256",
    )
    start_probes = _mapping(after.get("predecessor_start_probes"), "after.predecessor_start_probes")
    _verify_predecessor_runtime_start_probe(
        _mapping(start_probes.get("stable"), "after.predecessor_start_probes.stable"),
        label="Stable",
        expected_image_sha256=expected_stable_image,
        expected_source_sha=expected_stable_source,
        expected_role=expected_rollback_stable_role,
        database_container_id=restored_container_id,
        database_container_started_at=cast(str, restored_started_at),
        system_identifier=cast(str, restored_system_identifier),
        postgres_snapshot_fingerprint=before_snapshot,
        extension_schema_sha256=restored_extension_schema,
    )
    _verify_predecessor_runtime_start_probe(
        _mapping(start_probes.get("beta"), "after.predecessor_start_probes.beta"),
        label="Beta predecessor",
        expected_image_sha256=expected_beta_image,
        expected_source_sha=expected_beta_source,
        expected_role=expected_rollback_beta_role,
        database_container_id=restored_container_id,
        database_container_started_at=cast(str, restored_started_at),
        system_identifier=cast(str, restored_system_identifier),
        postgres_snapshot_fingerprint=before_snapshot,
        extension_schema_sha256=restored_extension_schema,
    )


def verify_canary_events(events: Sequence[str]) -> dict[str, int | bool]:
    """Validate a proposed/recorded final canary trace without executing it."""

    replacements = removes = invites = 0
    reset_recovered = False
    join_confirmed = False
    invite_sent = False
    remove_reconciled = False
    invite_reconciled = False

    for index, event in enumerate(events):
        if event == "reset_recovered":
            reset_recovered = True
        elif event == "replacement_started":
            _require(not reset_recovered, f"event {index}: replacement started after reset recovery")
            replacements += 1
            _require(replacements <= 1, "canary started more than one replacement workflow")
        elif event == "remove_sent":
            _require(not reset_recovered, f"event {index}: remove sent after reset recovery")
            _require(replacements == 1, f"event {index}: remove sent outside the one replacement workflow")
            removes += 1
            _require(removes <= 1, "canary sent more than one remove request")
        elif event == "invite_sent":
            _require(not reset_recovered, f"event {index}: invite sent after reset recovery")
            _require(removes == 1, f"event {index}: invite sent before the single remove boundary")
            _require(remove_reconciled, f"event {index}: invite sent before authoritative remove reconciliation")
            invites += 1
            invite_sent = True
            _require(invites <= 1, "canary sent more than one invitation request")
        elif event == "remove_capture_failed":
            _require(removes == 1, f"event {index}: remove capture failed before a remove request")
        elif event == "remove_reconciled":
            _require(removes == 1, f"event {index}: remove reconciled before a remove request")
            remove_reconciled = True
        elif event == "invite_capture_failed":
            _require(invites == 1, f"event {index}: invite capture failed before an invitation request")
        elif event == "invite_reconciled":
            _require(invites == 1, f"event {index}: invite reconciled before an invitation request")
            invite_reconciled = True
        elif event == "stop_after_remove":
            _require(remove_reconciled, f"event {index}: remove-only stop requires authoritative reconciliation")
        elif event == "stop_after_invite":
            _require(invite_reconciled, f"event {index}: invite-only stop requires authoritative reconciliation")
        elif event == "join_confirmed":
            _require(invite_sent, f"event {index}: join confirmed without an invitation")
            join_confirmed = True
        elif event == "mark_success":
            _require(join_confirmed, "canary marked success without authoritative join confirmation")
        elif event in {"threshold_probe", "discovery_churn"}:
            raise QualificationError("threshold-discovery churn is forbidden during the live canary")
        else:
            raise QualificationError(f"unknown canary event: {event}")

    return {
        "replacement_workflows": replacements,
        "remove_requests": removes,
        "invite_requests": invites,
        "reset_recovered": reset_recovered,
        "join_confirmed": join_confirmed,
        "remove_reconciled": remove_reconciled,
        "invite_reconciled": invite_reconciled,
    }


def authorize_canary_effect(events: Sequence[str], effect: CanaryEffect) -> GateDecision:
    """Authorize only the next unconsumed canary effect from the recorded trace prefix."""

    state = verify_canary_events(events)
    _require(not state["reset_recovered"], f"{effect}: effect is forbidden after reset recovery")
    _require(state["replacement_workflows"] == 1, f"{effect}: one replacement workflow is not active")
    if effect == "remove":
        _require(state["remove_requests"] == 0, "remove budget already consumed; retry is forbidden")
        _require(state["invite_requests"] == 0, "remove cannot be authorized after invitation activity")
        return GateDecision(True, "remove_authorized")

    _require(state["remove_requests"] == 1, "invite requires the single remove boundary")
    _require(state["remove_reconciled"] is True, "invite requires authoritative remove reconciliation")
    _require(state["invite_requests"] == 0, "invite budget already consumed; retry is forbidden")
    return GateDecision(True, "invite_authorized")


def _command_p4(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = verify_p4_artifact(
        artifact=Path(args.artifact).resolve(),
        manifest=Path(args.manifest).resolve(),
        ops_worktree=Path(args.ops_worktree).resolve(),
    )
    if args.base_source or args.scratch_root:
        _require(
            bool(args.base_source and args.scratch_root),
            "P4 replay requires both --base-source and --scratch-root",
        )
        result.update(
            replay_p4_patch(
                artifact=Path(args.artifact).resolve(),
                base_source=Path(args.base_source).resolve(),
                scratch_root=Path(args.scratch_root).resolve(),
            )
        )
    return result


def _command_preflight(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.source_root).resolve()
    verify_source_candidate(
        root,
        expected_source_sha=args.expected_source_sha,
        expected_package_version=args.expected_package_version,
    )
    return verify_preflight(
        _load_json(Path(args.evidence).resolve()),
        expected_source_sha=args.expected_source_sha,
        expected_package_version=args.expected_package_version,
        expected_image_sha256=args.expected_image_sha256,
        expected_workspace_account_id=args.expected_workspace_account_id,
        expected_stable_sha256=args.expected_stable_sha256,
        expected_beta_sha256=args.expected_beta_sha256,
        expected_postgres_container_id=args.expected_postgres_container_id,
        expected_postgres_system_identifier=args.expected_postgres_system_identifier,
        expected_rollback_stable_sha256=args.expected_rollback_stable_sha256,
        expected_rollback_beta_sha256=args.expected_rollback_beta_sha256,
        expected_rollback_stable_source_sha=args.expected_rollback_stable_source_sha,
        expected_rollback_beta_source_sha=args.expected_rollback_beta_source_sha,
        expected_rollback_stable_role=args.expected_rollback_stable_role,
        expected_rollback_beta_role=args.expected_rollback_beta_role,
    )


def _command_rollback(args: argparse.Namespace) -> dict[str, Any]:
    verify_rollback_state(
        _load_json(Path(args.before).resolve()),
        _load_json(Path(args.after).resolve()),
        expected_rollback_stable_sha256=args.expected_rollback_stable_sha256,
        expected_rollback_beta_sha256=args.expected_rollback_beta_sha256,
        expected_rollback_stable_source_sha=args.expected_rollback_stable_source_sha,
        expected_rollback_beta_source_sha=args.expected_rollback_beta_source_sha,
        expected_rollback_stable_role=args.expected_rollback_stable_role,
        expected_rollback_beta_role=args.expected_rollback_beta_role,
    )
    return {"rollback_state": "preserved"}


def _command_canary(args: argparse.Namespace) -> dict[str, Any]:
    data = _load_json(Path(args.events).resolve())
    events = data.get("events")
    _require(isinstance(events, list) and all(isinstance(item, str) for item in events), "events must be strings")
    trace = cast(list[str], events)
    result: dict[str, Any] = dict(verify_canary_events(trace))
    if args.next_effect == "none":
        result.update(effect_authorized=False, authorization_code="validation_only")
        return result
    decision = authorize_canary_effect(trace, cast(CanaryEffect, args.next_effect))
    result.update(effect_authorized=decision.authorized, authorization_code=decision.code)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p4 = subparsers.add_parser("p4", help="verify frozen P4 artifact/provenance")
    p4.add_argument("--artifact", required=True)
    p4.add_argument("--manifest", required=True)
    p4.add_argument("--ops-worktree", required=True)
    p4.add_argument("--base-source", help="exact reconstructed current Companion source for isolated patch replay")
    p4.add_argument("--scratch-root", help="existing directory used only for an auto-cleaned private replay copy")
    p4.set_defaults(handler=_command_p4)

    preflight = subparsers.add_parser("preflight", help="verify read-only G2 deployment preflight evidence")
    preflight.add_argument("--evidence", required=True)
    preflight.add_argument("--source-root", required=True)
    preflight.add_argument("--expected-source-sha", required=True)
    preflight.add_argument("--expected-package-version", required=True)
    preflight.add_argument("--expected-image-sha256", required=True)
    preflight.add_argument("--expected-workspace-account-id", required=True)
    preflight.add_argument("--expected-stable-sha256", required=True)
    preflight.add_argument("--expected-beta-sha256", required=True)
    preflight.add_argument("--expected-postgres-container-id", required=True)
    preflight.add_argument("--expected-postgres-system-identifier", required=True)
    preflight.add_argument("--expected-rollback-stable-sha256", required=True)
    preflight.add_argument("--expected-rollback-beta-sha256", required=True)
    preflight.add_argument("--expected-rollback-stable-source-sha", required=True)
    preflight.add_argument("--expected-rollback-beta-source-sha", required=True)
    preflight.add_argument("--expected-rollback-stable-role", required=True)
    preflight.add_argument("--expected-rollback-beta-role", required=True)
    preflight.set_defaults(handler=_command_preflight)

    rollback = subparsers.add_parser("rollback", help="compare durable state fingerprints around rollback")
    rollback.add_argument("--before", required=True)
    rollback.add_argument("--after", required=True)
    rollback.add_argument("--expected-rollback-stable-sha256", required=True)
    rollback.add_argument("--expected-rollback-beta-sha256", required=True)
    rollback.add_argument("--expected-rollback-stable-source-sha", required=True)
    rollback.add_argument("--expected-rollback-beta-source-sha", required=True)
    rollback.add_argument("--expected-rollback-stable-role", required=True)
    rollback.add_argument("--expected-rollback-beta-role", required=True)
    rollback.set_defaults(handler=_command_rollback)

    canary = subparsers.add_parser("canary", help="validate a final canary event trace")
    canary.add_argument("--events", required=True)
    canary.add_argument(
        "--next-effect",
        choices=("none", "remove", "invite"),
        required=True,
        help="'none' validates only; remove/invite explicitly authorizes only the next unconsumed effect",
    )
    canary.set_defaults(handler=_command_canary)

    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (QualificationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"member_rotation_qualification=FAIL {exc}", file=sys.stderr)
        return 1
    print("member_rotation_qualification=PASS " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
