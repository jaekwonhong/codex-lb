from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationAdmissionEvidence,
    MembershipMutationCommand,
    MembershipSubject,
)
from app.modules.workspace_member_controller.mutation_service import MembershipMutationError
from app.modules.workspace_member_controller.ports import WorkspaceReadPort


class WorkspaceMembershipMutationAdmission:
    """Exact workspace/member admission independent of inference-account state."""

    def __init__(
        self,
        reads: WorkspaceReadPort,
        *,
        clock=None,
        observation_max_age: timedelta = timedelta(seconds=30),
    ) -> None:
        self._reads = reads
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._observation_max_age = observation_max_age

    async def validate(self, command: MembershipMutationCommand) -> MembershipMutationAdmissionEvidence:
        mutation = command.mutation
        catalog = await self._reads.catalog()
        if not catalog.enabled:
            raise MembershipMutationError("workspace_catalog_disabled")
        if catalog.catalog_fingerprint != mutation.catalog_fingerprint:
            raise MembershipMutationError("catalog_identity_mismatch")
        matches = [workspace for workspace in catalog.workspaces if workspace.id == mutation.workspace_id]
        if len(matches) != 1:
            raise MembershipMutationError("workspace_not_found" if not matches else "workspace_identity_ambiguous")
        workspace = matches[0]
        if workspace.workspace_account_id != mutation.workspace_account_id:
            raise MembershipMutationError("workspace_account_identity_mismatch")

        if mutation.incoming is not None:
            if mutation.incoming.email.casefold() == workspace.owner_email.casefold():
                raise MembershipMutationError("owner_membership_mutation_forbidden")
            candidates = [
                member
                for member in workspace.members
                if member.preset_id == mutation.incoming.preset_id
                and member.email.casefold() == mutation.incoming.email.casefold()
                and member.user_id == mutation.incoming.user_id
            ]
            if len(candidates) != 1:
                raise MembershipMutationError("incoming_member_identity_mismatch")

        observed = await self._reads.observe_membership(workspace.id)
        if (
            observed.workspace_id != workspace.id
            or observed.workspace_account_id != workspace.workspace_account_id
            or observed.catalog_fingerprint != catalog.catalog_fingerprint
        ):
            raise MembershipMutationError("membership_observation_identity_mismatch")
        if (
            not observed.available
            or not observed.complete
            or not observed.owner_verified
            or observed.identity_ambiguous
            or observed.partial_identity
            or observed.duplicate_identity
            or observed.unknown_member
        ):
            raise MembershipMutationError("membership_observation_not_authoritative")
        age = self._clock() - observed.observed_at
        if age < timedelta(0) or age > self._observation_max_age:
            raise MembershipMutationError("membership_observation_expired")

        if mutation.outgoing is not None and not self._observed_exact(observed.members, mutation.outgoing):
            raise MembershipMutationError("outgoing_member_not_observed")
        return MembershipMutationAdmissionEvidence(
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
            catalog_fingerprint=catalog.catalog_fingerprint,
            membership_observed_at=observed.observed_at,
        )

    @staticmethod
    def _observed_exact(members, expected: MembershipSubject) -> bool:
        matches = [
            member
            for member in members
            if member.classification != "owner"
            and member.email.casefold() == expected.email.casefold()
            and member.user_id == expected.user_id
            and (expected.preset_id is None or member.preset_id in {None, expected.preset_id})
        ]
        return len(matches) == 1
