from __future__ import annotations

from typing import Protocol

from app.modules.workspace_member_controller.mutation_models import (
    MembershipMutationAdmissionEvidence,
    MembershipMutationCommand,
    MembershipMutationReceipt,
)


class MembershipMutationAdmissionPort(Protocol):
    """Revalidate exact workspace/member identity immediately before a claim."""

    async def validate(self, command: MembershipMutationCommand) -> MembershipMutationAdmissionEvidence: ...


class MembershipMutationEffectPort(Protocol):
    """Qualified workspace membership effect boundary.

    ``execute`` may be called only after a durable journal claim. ``reconcile``
    is observational: it must never resend the mutation.
    """

    async def execute(self, command: MembershipMutationCommand) -> MembershipMutationReceipt: ...

    async def reconcile(
        self,
        *,
        operation_id: str,
        command_id: str,
        request_fingerprint: str,
    ) -> MembershipMutationReceipt | None: ...
