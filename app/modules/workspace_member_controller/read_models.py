from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.modules.workspace_member_controller.domain import ControllerModel


class WorkspaceIntentView(ControllerModel):
    workspace_id: str
    workspace_account_id: str
    enabled: bool
    version: int = Field(ge=0)
    updated_at: datetime | None = None


class ActiveMembershipOperationView(ControllerModel):
    operation_id: str
    kind: str
    revision: int = Field(ge=0)
    pending_action: str | None = None
    command_id: str | None = None


class WorkspaceReadStatus(ControllerModel):
    workspace_id: str
    workspace_account_id: str
    workspace_name: str
    owner_email: str
    membership_code: str
    membership_observed_at: datetime | None = None
    intent: WorkspaceIntentView


class ControllerReadStatus(ControllerModel):
    schema_version: Literal[1] = 1
    catalog_fingerprint: str
    enabled: bool
    active_operation: ActiveMembershipOperationView | None = None
    workspaces: list[WorkspaceReadStatus]

