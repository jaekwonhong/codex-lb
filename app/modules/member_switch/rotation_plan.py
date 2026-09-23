from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.usage.weekly_observation import UsageAccountIdentity
from app.modules.member_switch.schemas import CompanionTypedTelemetryProvenance

SCHEDULE_BINDING_ID = "rotation-q3-single-evaluation"


class CanaryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    enabled: bool = Field(default=False, strict=True)
    evaluation_id: UUID
    workspace_id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    outgoing_account_id: str = Field(min_length=1)
    outgoing_email: str = Field(min_length=1)
    outgoing_user_id: str = Field(min_length=1)
    membership_epoch: str = Field(min_length=1)
    expires_at: AwareDatetime
    provenance: CompanionTypedTelemetryProvenance

    @property
    def member(self) -> UsageAccountIdentity:
        return UsageAccountIdentity(
            self.outgoing_account_id, self.workspace_account_id, self.outgoing_user_id, self.outgoing_email
        )


def read_canary_plan(directory: Path) -> CanaryPlan | None:
    try:
        with (directory / "canary-plan.json").open("rb") as stream:
            raw = stream.read(16385)
    except FileNotFoundError:
        return None
    if len(raw) > 16384:
        raise ValueError("rotation_plan_oversized")
    plan = CanaryPlan.model_validate_json(raw)
    return plan if plan.enabled else None
