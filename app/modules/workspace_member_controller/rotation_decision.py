from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import ConfigDict, Field

from app.modules.workspace_member_controller.account_binding import (
    WorkspaceMemberAccountBinding,
    WorkspaceMemberAccountBindingPort,
)
from app.modules.workspace_member_controller.account_state import (
    AccountDecisionEvidence,
    OpenCodexAccountState,
    OpenCodexAccountStateError,
    OpenCodexAccountStatePort,
    read_stable_account_state,
)
from app.modules.workspace_member_controller.domain import ControllerModel, MembershipObservation, Workspace
from app.modules.workspace_member_controller.ports import WorkspaceReadPort

RotationDecisionState = Literal[
    "account_binding_missing",
    "account_state_unavailable",
    "account_state_unstable",
    "account_state_stale",
    "account_state_blocked",
    "quota_unknown",
    "quota_available",
    "reset_credit_unknown",
    "reset_required",
    "mutation_budget_blocked",
    "admission_ready",
]


class RotationMemberIdentity(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1)
    workspace_account_id: str = Field(min_length=1)
    preset_id: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    user_id: str = Field(pattern=r"^user-[A-Za-z0-9]+$")


class RotationDecisionRequest(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_id: str = Field(min_length=1)
    budget_operation_id: str = Field(min_length=1)
    member: RotationMemberIdentity
    catalog_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class MembershipMutationBudgetDecision(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    admitted: bool
    code: str = Field(min_length=1)
    count_24h: int = Field(ge=0)
    count_168h: int = Field(ge=0)
    coverage_started_at: datetime | None = None


class MembershipMutationBudgetPort(Protocol):
    async def reserve(
        self,
        *,
        operation_id: str,
        evaluation_id: str,
        workspace_id: str,
        workspace_account_id: str,
    ) -> MembershipMutationBudgetDecision: ...


class RotationDecision(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    evaluation_id: str
    state: RotationDecisionState
    admission_ready: bool
    attention_required: bool
    code: str
    binding: WorkspaceMemberAccountBinding | None = None
    account_evidence: AccountDecisionEvidence | None = None
    budget: MembershipMutationBudgetDecision | None = None
    membership_observed_at: datetime | None = None


class RotationDecisionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkspaceMemberRotationDecisionService:
    """Pure control-plane decision over Controller identity + OpenCodex state."""

    _QUOTA_ONLY_EXCLUSIONS = frozenset({"quota_exhausted", "cooldown"})

    def __init__(
        self,
        reads: WorkspaceReadPort,
        bindings: WorkspaceMemberAccountBindingPort,
        accounts: OpenCodexAccountStatePort,
        budget: MembershipMutationBudgetPort,
        *,
        clock: Callable[[], datetime] | None = None,
        account_state_max_age: timedelta = timedelta(seconds=30),
        quota_state_max_age: timedelta = timedelta(seconds=180),
        membership_max_age: timedelta = timedelta(seconds=30),
    ) -> None:
        self._reads = reads
        self._bindings = bindings
        self._accounts = accounts
        self._budget = budget
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._account_state_max_age = account_state_max_age
        self._quota_state_max_age = quota_state_max_age
        self._membership_max_age = membership_max_age

    async def evaluate(self, request: RotationDecisionRequest) -> RotationDecision:
        workspace, observed = await self._current_member(request)
        binding = await self._bindings.get_exact(
            workspace_id=request.member.workspace_id,
            workspace_account_id=request.member.workspace_account_id,
            preset_id=request.member.preset_id,
            member_user_id=request.member.user_id,
            member_email_normalized=request.member.email.strip().casefold(),
        )
        if binding is None:
            return self._decision(request, "account_binding_missing", True, observed=observed)
        self._require_binding_identity(binding, request)

        try:
            state = await read_stable_account_state(self._accounts, binding.opencodex_account_id)
        except OpenCodexAccountStateError as exc:
            if exc.code == "opencodex_account_identity_mismatch":
                raise RotationDecisionError("rotation_account_state_identity_mismatch") from exc
            if exc.code == "opencodex_account_state_unstable":
                return self._decision(
                    request,
                    "account_state_unstable",
                    True,
                    binding=binding,
                    observed=observed,
                )
            return self._decision(
                request,
                "account_state_unavailable",
                True,
                binding=binding,
                observed=observed,
            )
        if state.account_id != binding.opencodex_account_id:
            raise RotationDecisionError("rotation_account_state_identity_mismatch")
        evidence = self._evidence(state)
        now_ms = self._now_ms()
        if not state.is_fresh(now_ms=now_ms, max_age_ms=self._milliseconds(self._account_state_max_age)):
            return self._decision(
                request,
                "account_state_stale",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if not state.has_credential or state.needs_reauth or state.paused or state.selection_state == "unknown":
            return self._decision(
                request,
                "account_state_blocked",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if not state.is_main and state.credential_generation is None:
            return self._decision(
                request,
                "account_state_blocked",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        foreign_exclusions = set(state.exclusion_reasons) - self._QUOTA_ONLY_EXCLUSIONS
        if foreign_exclusions:
            return self._decision(
                request,
                "account_state_blocked",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if state.quota_state == "unknown" or not state.quota_is_fresh(
            now_ms=now_ms,
            max_age_ms=self._milliseconds(self._quota_state_max_age),
        ):
            return self._decision(
                request,
                "quota_unknown",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if state.quota_state == "available":
            return self._decision(
                request,
                "quota_available",
                False,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if state.selection_state != "excluded":
            return self._decision(
                request,
                "account_state_blocked",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if state.reset_credit_state is None:
            return self._decision(
                request,
                "reset_credit_unknown",
                True,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )
        if state.reset_credit_state.available_count > 0:
            return self._decision(
                request,
                "reset_required",
                False,
                binding=binding,
                evidence=evidence,
                observed=observed,
            )

        budget = await self._budget.reserve(
            operation_id=request.budget_operation_id,
            evaluation_id=request.evaluation_id,
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
        )
        if not budget.admitted:
            return self._decision(
                request,
                "mutation_budget_blocked",
                False,
                binding=binding,
                evidence=evidence,
                budget=budget,
                observed=observed,
            )
        return self._decision(
            request,
            "admission_ready",
            False,
            binding=binding,
            evidence=evidence,
            budget=budget,
            observed=observed,
            admission_ready=True,
        )

    async def revalidate_account_evidence(self, evidence: AccountDecisionEvidence) -> OpenCodexAccountState:
        try:
            state = await read_stable_account_state(self._accounts, evidence.account_id)
        except OpenCodexAccountStateError as exc:
            if exc.code == "opencodex_account_identity_mismatch":
                raise RotationDecisionError("rotation_account_state_identity_mismatch") from exc
            if exc.code == "opencodex_account_state_unstable":
                raise RotationDecisionError("rotation_account_state_unstable") from exc
            raise RotationDecisionError("rotation_account_state_unavailable") from exc
        except Exception as exc:
            raise RotationDecisionError("rotation_account_state_unavailable") from exc
        now_ms = self._now_ms()
        if not state.is_fresh(now_ms=now_ms, max_age_ms=self._milliseconds(self._account_state_max_age)):
            raise RotationDecisionError("rotation_account_state_stale")
        if not state.quota_is_fresh(now_ms=now_ms, max_age_ms=self._milliseconds(self._quota_state_max_age)):
            raise RotationDecisionError("rotation_quota_state_stale")
        current = self._evidence(state)
        if (
            current.account_id != evidence.account_id
            or current.credential_generation != evidence.credential_generation
            or current.main_identity_generation != evidence.main_identity_generation
            or current.state_revision != evidence.state_revision
        ):
            raise RotationDecisionError("rotation_account_evidence_changed")
        if current.quota_state != "exhausted" or current.reset_credit_available_count != 0:
            raise RotationDecisionError("rotation_account_preconditions_changed")
        return state

    async def _current_member(
        self,
        request: RotationDecisionRequest,
    ) -> tuple[Workspace, MembershipObservation]:
        catalog = await self._reads.catalog()
        member = request.member
        if not catalog.enabled or catalog.catalog_fingerprint != request.catalog_fingerprint:
            raise RotationDecisionError("rotation_catalog_identity_mismatch")
        matches = [
            workspace
            for workspace in catalog.workspaces
            if workspace.id == member.workspace_id
            and workspace.workspace_account_id == member.workspace_account_id
        ]
        if len(matches) != 1:
            raise RotationDecisionError("rotation_workspace_identity_mismatch")
        workspace = matches[0]
        candidates = [
            candidate
            for candidate in workspace.members
            if candidate.preset_id == member.preset_id
            and candidate.email.casefold() == member.email.casefold()
            and candidate.user_id == member.user_id
        ]
        if len(candidates) != 1:
            raise RotationDecisionError("rotation_member_identity_mismatch")
        observed = await self._reads.observe_membership(workspace.id)
        if (
            observed.workspace_id != workspace.id
            or observed.workspace_account_id != workspace.workspace_account_id
            or observed.catalog_fingerprint != catalog.catalog_fingerprint
            or not observed.available
            or not observed.complete
            or not observed.owner_verified
            or observed.identity_ambiguous
            or observed.partial_identity
            or observed.duplicate_identity
            or observed.unknown_member
        ):
            raise RotationDecisionError("rotation_membership_observation_not_authoritative")
        age = self._clock() - observed.observed_at
        if age < timedelta(0) or age > self._membership_max_age:
            raise RotationDecisionError("rotation_membership_observation_expired")
        current = [
            item
            for item in observed.members
            if item.classification != "owner"
            and item.email.casefold() == member.email.casefold()
            and item.user_id == member.user_id
            and item.preset_id in {None, member.preset_id}
        ]
        if len(current) != 1:
            raise RotationDecisionError("rotation_current_member_mismatch")
        return workspace, observed

    @staticmethod
    def _require_binding_identity(
        binding: WorkspaceMemberAccountBinding,
        request: RotationDecisionRequest,
    ) -> None:
        member = request.member
        if (
            binding.workspace_id != member.workspace_id
            or binding.workspace_account_id != member.workspace_account_id
            or binding.preset_id != member.preset_id
            or binding.member_user_id != member.user_id
            or binding.member_email_normalized != member.email.strip().casefold()
            or binding.role != "member"
        ):
            raise RotationDecisionError("rotation_account_binding_identity_mismatch")

    @staticmethod
    def _evidence(state: OpenCodexAccountState) -> AccountDecisionEvidence:
        return AccountDecisionEvidence(
            account_id=state.account_id,
            credential_generation=state.credential_generation,
            main_identity_generation=state.main_identity_generation,
            state_revision=state.state_revision,
            observed_at=state.observed_at,
            quota_observed_at=state.quota_observed_at,
            selection_state=state.selection_state,
            quota_state=state.quota_state,
            needs_reauth=state.needs_reauth,
            paused=state.paused,
            quota_windows=state.quota_windows,
            reset_credit_available_count=(
                None if state.reset_credit_state is None else state.reset_credit_state.available_count
            ),
        )

    def _decision(
        self,
        request: RotationDecisionRequest,
        state: RotationDecisionState,
        attention: bool,
        *,
        binding: WorkspaceMemberAccountBinding | None = None,
        evidence: AccountDecisionEvidence | None = None,
        budget: MembershipMutationBudgetDecision | None = None,
        observed: MembershipObservation | None = None,
        admission_ready: bool = False,
    ) -> RotationDecision:
        return RotationDecision(
            evaluation_id=request.evaluation_id,
            state=state,
            admission_ready=admission_ready,
            attention_required=attention,
            code=f"rotation_{state}",
            binding=binding,
            account_evidence=evidence,
            budget=budget,
            membership_observed_at=None if observed is None else observed.observed_at,
        )

    def _now_ms(self) -> int:
        return int(self._clock().timestamp() * 1000)

    @staticmethod
    def _milliseconds(value: timedelta) -> int:
        return max(0, int(value.total_seconds() * 1000))
