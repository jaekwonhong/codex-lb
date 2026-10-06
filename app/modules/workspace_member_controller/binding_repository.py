from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.modules.workspace_member_controller.account_binding import (
    WorkspaceMemberAccountBinding,
    WorkspaceMemberAccountBindingPort,
)
from app.modules.workspace_member_controller.domain import ControllerModel

_MAX_BINDING_FILE_BYTES = 1_048_576


class WorkspaceMemberAccountBindingFile(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    bindings: list[WorkspaceMemberAccountBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_bindings(self) -> WorkspaceMemberAccountBindingFile:
        identities: set[tuple[str, str, str, str, str]] = set()
        account_subjects: dict[str, tuple[str, str]] = {}
        for binding in self.bindings:
            identity = (
                binding.workspace_id,
                binding.workspace_account_id,
                binding.preset_id,
                binding.member_user_id,
                binding.member_email_normalized,
            )
            if identity in identities:
                raise ValueError("duplicate_workspace_member_account_binding")
            identities.add(identity)
            subject = (binding.member_user_id, binding.member_email_normalized)
            existing = account_subjects.setdefault(binding.opencodex_account_id, subject)
            if existing != subject:
                raise ValueError("opencodex_account_bound_to_conflicting_subjects")
        return self


class FileWorkspaceMemberAccountBindingRepository(WorkspaceMemberAccountBindingPort):
    """Explicit operator-supplied bindings; never inferred from email or aliases."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> WorkspaceMemberAccountBindingFile:
        try:
            with self._path.open("rb") as handle:
                raw = handle.read(_MAX_BINDING_FILE_BYTES + 1)
        except OSError as exc:
            raise ValueError("account_binding_file_unavailable") from exc
        if len(raw) > _MAX_BINDING_FILE_BYTES:
            raise ValueError("account_binding_file_oversized")
        try:
            payload = json.loads(raw)
            return WorkspaceMemberAccountBindingFile.model_validate(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("account_binding_file_invalid") from exc

    async def get_exact(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
        preset_id: str,
        member_user_id: str,
        member_email_normalized: str,
    ) -> WorkspaceMemberAccountBinding | None:
        normalized = member_email_normalized.strip().casefold()
        matches = [
            binding
            for binding in self.snapshot().bindings
            if binding.workspace_id == workspace_id
            and binding.workspace_account_id == workspace_account_id
            and binding.preset_id == preset_id
            and binding.member_user_id == member_user_id
            and binding.member_email_normalized == normalized
        ]
        if len(matches) > 1:
            raise ValueError("workspace_member_account_binding_ambiguous")
        return matches[0] if matches else None
