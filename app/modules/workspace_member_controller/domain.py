from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator
from pydantic.alias_generators import to_camel


class ControllerModel(BaseModel):
    """Wire-compatible model base owned by the standalone Controller domain.

    It intentionally mirrors the existing camelCase/UTC wire behavior without
    inheriting Codex-LB's dashboard model, so the domain can move into a separate
    process without pulling dashboard or proxy dependencies with it.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        ser_json_timedelta="iso8601",
    )

    @field_serializer("*", when_used="json")
    def serialize_datetime_as_utc(value, _info):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.isoformat() + "Z"
            return value.isoformat().replace("+00:00", "Z")
        return value


class Member(ControllerModel):
    preset_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")


class CurrentMember(ControllerModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    preset_id: str | None = None
    auth_state: Literal[
        "active",
        "handoff_quarantined",
        "inactive",
        "absent",
        "ambiguous",
        "unmanaged",
        "unknown",
    ] = "unknown"
    auth_account_id: str | None = None


class OwnerAuthTarget(ControllerModel):
    preset_id: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")
    auth_state: Literal[
        "active",
        "handoff_quarantined",
        "inactive",
        "absent",
        "ambiguous",
        "unmanaged",
        "unknown",
    ] = "unknown"
    auth_account_id: str | None = None


class Workspace(ControllerModel):
    id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    workspace_name: str = Field(min_length=1)
    owner_email: str = Field(min_length=3)
    owner_auth: OwnerAuthTarget | None = None
    members: list[Member]
    current_members: list[CurrentMember] = Field(default_factory=list)
    membership_code: str = "not_checked"
    membership_observed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_owner_auth_boundary(self) -> Workspace:
        owner = self.owner_auth
        if owner is None:
            return self
        if owner.preset_id != f"owner:{self.id}" or owner.email.casefold() != self.owner_email.casefold():
            raise ValueError("owner_auth_identity_mismatch")
        if any(
            member.email.casefold() == owner.email.casefold() or member.user_id == owner.user_id
            for member in self.members
        ):
            raise ValueError("owner_auth_must_not_be_member_candidate")
        return self


class Catalog(ControllerModel):
    enabled: bool
    schema_version: Literal[1]
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    capabilities: list[str] = Field(default_factory=list)
    workspaces: list[Workspace]


class MembershipObservationMember(ControllerModel):
    email: str
    user_id: str
    preset_id: str | None = None
    classification: str


class MembershipObservation(ControllerModel):
    schema_version: Literal[1]
    available: bool
    code: str
    workspace_id: str
    workspace_account_id: str
    catalog_fingerprint: str
    observed_at: datetime
    complete: bool
    owner_verified: bool
    identity_ambiguous: bool
    partial_identity: bool
    duplicate_identity: bool
    unknown_member: bool
    members: list[MembershipObservationMember]


class Identity(ControllerModel):
    workspace_id: str
    workspace_account_id: str
    preset_id: str
    target_email: str
    target_user_id: str
    catalog_fingerprint: str

