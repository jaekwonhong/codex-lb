from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

from pydantic import ConfigDict, Field

from app.modules.shared.schemas import DashboardModel

_CATALOG_SCHEMA_VERSION = 1


class CustomMemberAuthCatalogRecord(DashboardModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: str = Field(min_length=1)
    preset_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    owner_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    workspace_account_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )


class _CustomMemberAuthCatalogFile(DashboardModel):
    schema_version: int = Field(default=_CATALOG_SCHEMA_VERSION, ge=1)
    members: tuple[CustomMemberAuthCatalogRecord, ...] = ()


class MemberAuthCatalogOverlayRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> tuple[CustomMemberAuthCatalogRecord, ...]:
        with self._lock:
            if not self._path.exists():
                return ()
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            catalog_file = _CustomMemberAuthCatalogFile.model_validate(payload)
            if catalog_file.schema_version != _CATALOG_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported member auth catalog schema: {catalog_file.schema_version}"
                )
            return catalog_file.members

    def save(self, members: tuple[CustomMemberAuthCatalogRecord, ...]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = _CustomMemberAuthCatalogFile(members=members).model_dump(
                mode="json",
                by_alias=True,
            )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=self._path.parent,
                text=True,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self._path)
            finally:
                temporary_path.unlink(missing_ok=True)
