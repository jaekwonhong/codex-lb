"""Host-signed observations; release constants alone are never runtime proof."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.member_switch.schemas import CompanionTypedTelemetryProvenance


class HostRuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    endpoint: str
    provenance: CompanionTypedTelemetryProvenance
    pid: int = Field(gt=0, strict=True)
    process_started: str = Field(min_length=1)
    executable_device: int = Field(ge=0, strict=True)
    executable_inode: int = Field(gt=0, strict=True)
    observed_at: AwareDatetime
    expires_at: AwareDatetime


class SignedHostObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation: HostRuntimeObservation
    signature: str


def observation_bytes(observation: HostRuntimeObservation) -> bytes:
    return json.dumps(
        observation.model_dump(mode="json", exclude_none=True), sort_keys=True, separators=(",", ":")
    ).encode()


class RuntimeAttestation(Protocol):
    def require(self, expected: CompanionTypedTelemetryProvenance) -> HostRuntimeObservation: ...


class MissingRuntimeAttestation:
    def require(self, expected: CompanionTypedTelemetryProvenance) -> HostRuntimeObservation:
        raise ValueError("rotation_runtime_attestation_unavailable")


class FileRuntimeAttestation:
    """The public key is an operator trust root mounted read-only into the backend.

    The private key stays with the external host verifier. Each call reads again;
    old accepted observations and stored controller flags never authorize a start.
    """

    def __init__(
        self,
        directory: Path,
        endpoint: str | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.directory = directory
        self.endpoint = endpoint
        self.clock = clock

    def require(self, expected: CompanionTypedTelemetryProvenance) -> HostRuntimeObservation:
        try:
            key_bytes = (self.directory / "host-verifier.pub").read_bytes()
            # Bound local input size before JSON parsing.
            with (self.directory / "host-observation.json").open("rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("oversized observation")
            signed = SignedHostObservation.model_validate_json(raw)
            key = Ed25519PublicKey.from_public_bytes(key_bytes)
            key.verify(base64.b64decode(signed.signature, validate=True), observation_bytes(signed.observation))
            observed = signed.observation
            now = self.clock()
            if (
                not expected.qualified
                or observed.provenance != expected
                or self.endpoint is None
                or observed.endpoint != self.endpoint
                or not observed.observed_at <= now < observed.expires_at
                or not timedelta(0) < observed.expires_at - observed.observed_at <= timedelta(seconds=30)
            ):
                raise ValueError("runtime identity or freshness mismatch")
            return observed
        except (OSError, ValueError, InvalidSignature) as exc:
            raise ValueError("rotation_runtime_attestation_invalid") from exc
