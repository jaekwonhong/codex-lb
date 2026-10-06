from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.modules.workspace_member_controller.domain import ControllerModel

MembershipMutationAction = Literal["add", "remove", "switch"]
MembershipMutationPhase = Literal[
    "ready",
    "effect_pending",
    "outcome_unknown",
    "completed",
    "failed",
]
MembershipEffectState = Literal[
    "not_attempted",
    "unknown",
    "confirmed",
    "authoritative_non_effect",
]
MembershipMutationOutcome = Literal["completed", "authoritative_non_effect", "outcome_unknown"]


class MembershipSubject(ControllerModel):
    preset_id: str | None = Field(default=None, min_length=1)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")


class MembershipMutationSpec(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    action: MembershipMutationAction
    workspace_id: str = Field(min_length=1, max_length=100)
    workspace_account_id: str = Field(min_length=1)
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    incoming: MembershipSubject | None = None
    outgoing: MembershipSubject | None = None

    @model_validator(mode="after")
    def validate_action_shape(self) -> MembershipMutationSpec:
        if self.action == "add" and (self.incoming is None or self.outgoing is not None):
            raise ValueError("add_requires_only_incoming_member")
        if self.action == "remove" and (self.outgoing is None or self.incoming is not None):
            raise ValueError("remove_requires_only_outgoing_member")
        if self.action == "switch":
            if self.incoming is None or self.outgoing is None:
                raise ValueError("switch_requires_incoming_and_outgoing_members")
            if (
                self.incoming.email.casefold() == self.outgoing.email.casefold()
                or self.incoming.user_id == self.outgoing.user_id
            ):
                raise ValueError("switch_members_must_be_distinct")
        return self


class MembershipMutationCommand(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    command_id: UUID
    expected_revision: int = Field(ge=0)
    mutation: MembershipMutationSpec

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class MembershipMutationReceipt(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    operation_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: MembershipMutationAction
    workspace_id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    outcome: MembershipMutationOutcome
    code: str = Field(min_length=1)
    observed_at: datetime
    remove_effect: MembershipEffectState = "not_attempted"
    add_effect: MembershipEffectState = "not_attempted"
    final_membership_confirmed: bool = False

    @model_validator(mode="after")
    def validate_outcome_evidence(self) -> MembershipMutationReceipt:
        if self.action == "add" and self.remove_effect != "not_attempted":
            raise ValueError("add_receipt_contains_remove_effect")
        if self.action == "remove" and self.add_effect != "not_attempted":
            raise ValueError("remove_receipt_contains_add_effect")
        if self.outcome == "completed":
            required = {
                "add": self.add_effect == "confirmed" and self.remove_effect == "not_attempted",
                "remove": self.remove_effect == "confirmed" and self.add_effect == "not_attempted",
                "switch": self.remove_effect == "confirmed" and self.add_effect == "confirmed",
            }[self.action]
            if not required or not self.final_membership_confirmed:
                raise ValueError("completed_receipt_missing_effect_confirmation")
        elif self.outcome == "authoritative_non_effect":
            if self.final_membership_confirmed:
                raise ValueError("non_effect_receipt_cannot_confirm_membership")
            if "confirmed" in {self.remove_effect, self.add_effect} or "unknown" in {
                self.remove_effect,
                self.add_effect,
            }:
                raise ValueError("non_effect_receipt_contains_effect_evidence")
        elif self.final_membership_confirmed:
            raise ValueError("unknown_receipt_cannot_confirm_final_membership")
        return self


class MembershipMutationAdmissionEvidence(ControllerModel):
    schema_version: Literal[1] = 1
    workspace_id: str
    workspace_account_id: str
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    membership_observed_at: datetime


class MembershipMutationState(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    control_protocol: Literal["workspace_membership_mutation_v1"] = "workspace_membership_mutation_v1"
    operation_id: str = Field(min_length=1)
    mutation: MembershipMutationSpec
    command_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    phase: MembershipMutationPhase
    last_code: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    admission: MembershipMutationAdmissionEvidence
    receipt: MembershipMutationReceipt | None = None

    @model_validator(mode="after")
    def validate_persisted_evidence(self) -> MembershipMutationState:
        if (
            self.admission.workspace_id != self.mutation.workspace_id
            or self.admission.workspace_account_id != self.mutation.workspace_account_id
            or self.admission.catalog_fingerprint != self.mutation.catalog_fingerprint
        ):
            raise ValueError("mutation_admission_identity_mismatch")
        if self.receipt is not None and (
            self.receipt.operation_id != self.operation_id
            or self.receipt.request_fingerprint != self.command_fingerprint
            or self.receipt.action != self.mutation.action
            or self.receipt.workspace_id != self.mutation.workspace_id
            or self.receipt.workspace_account_id != self.mutation.workspace_account_id
        ):
            raise ValueError("mutation_receipt_identity_mismatch")
        if self.phase == "completed" and (self.receipt is None or self.receipt.outcome != "completed"):
            raise ValueError("completed_mutation_receipt_missing")
        if self.phase == "failed" and (
            self.receipt is None or self.receipt.outcome != "authoritative_non_effect"
        ):
            raise ValueError("failed_mutation_non_effect_receipt_missing")
        if self.phase in {"ready", "effect_pending"} and self.receipt is not None:
            raise ValueError("pre_settlement_mutation_cannot_have_receipt")
        if self.phase == "outcome_unknown" and self.receipt is not None and self.receipt.outcome != "outcome_unknown":
            raise ValueError("unknown_mutation_receipt_mismatch")
        return self


class MembershipMutationView(ControllerModel):
    schema_version: Literal[1] = 1
    operation_id: str
    revision: int = Field(ge=0)
    mutation: MembershipMutationSpec
    phase: MembershipMutationPhase
    last_code: str
    updated_at: datetime
    pending_action: str | None = None
    command_id: str | None = None
    receipt: MembershipMutationReceipt | None = None
