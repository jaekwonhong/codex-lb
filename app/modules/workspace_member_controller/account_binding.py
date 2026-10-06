from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, field_validator

from app.modules.workspace_member_controller.domain import ControllerModel


class WorkspaceMemberAccountBinding(ControllerModel):
    """Durable Controller-owned join from one workspace identity to OpenCodex."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    workspace_id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    preset_id: str = Field(min_length=1)
    member_user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    member_email_normalized: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["owner", "member"] = "member"
    opencodex_account_id: str = Field(min_length=1)
    established_at: datetime

    @field_validator("member_email_normalized")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class WorkspaceMemberAccountBindingPort(Protocol):
    async def get_exact(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
        preset_id: str,
        member_user_id: str,
        member_email_normalized: str,
    ) -> WorkspaceMemberAccountBinding | None: ...
