from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.modules.workspace_member_controller.domain import (
    Catalog,
    Member,
    MembershipObservation,
    MembershipObservationMember,
    Workspace,
)
from app.modules.workspace_member_controller.mutation_admission import WorkspaceMembershipMutationAdmission
from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationCommand,
    MembershipMutationSpec,
    MembershipSubject,
)
from app.modules.workspace_member_controller.mutation_service import MembershipMutationError

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)


def command() -> MembershipMutationCommand:
    return MembershipMutationCommand(
        operation_id=UUID("11111111-1111-4111-8111-111111111111"),
        command_id=UUID("22222222-2222-4222-8222-222222222222"),
        expected_revision=0,
        mutation=MembershipMutationSpec(
            action="switch",
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="a" * 64,
            incoming=MembershipSubject(
                preset_id="incoming",
                email="incoming@example.com",
                user_id="user-Incoming",
            ),
            outgoing=MembershipSubject(
                preset_id="outgoing",
                email="outgoing@example.com",
                user_id="user-Outgoing",
            ),
        ),
    )


class Reads:
    def __init__(self):
        self.observed_at = NOW
        self.complete = True
        self.owner_verified = True
        self.identity_ambiguous = False
        self.members = [
            MembershipObservationMember(
                email="owner@example.com",
                user_id="user-Owner",
                classification="owner",
            ),
            MembershipObservationMember(
                email="outgoing@example.com",
                user_id="user-Outgoing",
                preset_id="outgoing",
                classification="managed",
            ),
        ]

    async def catalog(self) -> Catalog:
        return Catalog(
            enabled=True,
            schema_version=1,
            catalog_fingerprint="a" * 64,
            workspaces=[
                Workspace(
                    id="workspace-1",
                    workspace_account_id="workspace-account-1",
                    workspace_name="Workspace One",
                    owner_email="owner@example.com",
                    members=[
                        Member(
                            preset_id="incoming",
                            display_name="Incoming",
                            email="incoming@example.com",
                            user_id="user-Incoming",
                        ),
                        Member(
                            preset_id="outgoing",
                            display_name="Outgoing",
                            email="outgoing@example.com",
                            user_id="user-Outgoing",
                        ),
                    ],
                )
            ],
        )

    async def observe_membership(self, workspace_id: str) -> MembershipObservation:
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id=workspace_id,
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="a" * 64,
            observed_at=self.observed_at,
            complete=self.complete,
            owner_verified=self.owner_verified,
            identity_ambiguous=self.identity_ambiguous,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=self.members,
        )


async def test_admission_binds_exact_catalog_workspace_and_live_outgoing_member():
    reads = Reads()
    evidence = await WorkspaceMembershipMutationAdmission(reads, clock=lambda: NOW).validate(command())
    assert evidence.workspace_id == "workspace-1"
    assert evidence.workspace_account_id == "workspace-account-1"
    assert evidence.catalog_fingerprint == "a" * 64
    assert evidence.membership_observed_at == NOW


async def test_admission_rejects_stale_or_non_authoritative_membership_observation():
    reads = Reads()
    reads.observed_at = NOW - timedelta(seconds=31)
    with pytest.raises(MembershipMutationError, match="membership_observation_expired"):
        await WorkspaceMembershipMutationAdmission(reads, clock=lambda: NOW).validate(command())

    reads.observed_at = NOW
    reads.identity_ambiguous = True
    with pytest.raises(MembershipMutationError, match="membership_observation_not_authoritative"):
        await WorkspaceMembershipMutationAdmission(reads, clock=lambda: NOW).validate(command())


async def test_admission_rejects_missing_outgoing_member_and_mismatched_incoming_identity():
    reads = Reads()
    reads.members = [member for member in reads.members if member.classification == "owner"]
    with pytest.raises(MembershipMutationError, match="outgoing_member_not_observed"):
        await WorkspaceMembershipMutationAdmission(reads, clock=lambda: NOW).validate(command())

    reads = Reads()
    changed = command().model_copy(
        update={
            "mutation": command().mutation.model_copy(
                update={
                    "incoming": MembershipSubject(
                        preset_id="incoming",
                        email="other@example.com",
                        user_id="user-Incoming",
                    )
                }
            )
        }
    )
    with pytest.raises(MembershipMutationError, match="incoming_member_identity_mismatch"):
        await WorkspaceMembershipMutationAdmission(reads, clock=lambda: NOW).validate(changed)


async def test_admission_rejects_owner_as_incoming_membership_target():
    reads = Reads()
    catalog = await reads.catalog()
    workspace = catalog.workspaces[0]
    workspace.members.append(
        Member(
            preset_id="owner-target",
            display_name="Owner Target",
            email="owner@example.com",
            user_id="user-OwnerTarget",
        )
    )

    async def catalog_with_owner_target():
        return catalog

    reads.catalog = catalog_with_owner_target  # type: ignore[method-assign]
    changed = command().model_copy(
        update={
            "mutation": command().mutation.model_copy(
                update={
                    "incoming": MembershipSubject(
                        preset_id="owner-target",
                        email="owner@example.com",
                        user_id="user-OwnerTarget",
                    )
                }
            )
        }
    )
    with pytest.raises(MembershipMutationError, match="owner_membership_mutation_forbidden"):
        await WorkspaceMembershipMutationAdmission(reads, clock=lambda: NOW).validate(changed)
