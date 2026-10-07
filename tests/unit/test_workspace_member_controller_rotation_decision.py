from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.workspace_member_controller.account_binding import WorkspaceMemberAccountBinding
from app.modules.workspace_member_controller.account_state import (
    OpenCodexAccountState,
    OpenCodexAccountStateError,
)
from app.modules.workspace_member_controller.domain import (
    Catalog,
    Member,
    MembershipObservation,
    MembershipObservationMember,
    Workspace,
)
from app.modules.workspace_member_controller.rotation_decision import (
    MembershipMutationBudgetDecision,
    RotationDecisionError,
    RotationDecisionRequest,
    RotationMemberIdentity,
    WorkspaceMemberRotationDecisionService,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def request() -> RotationDecisionRequest:
    return RotationDecisionRequest(
        evaluation_id="evaluation-1",
        budget_operation_id="budget-1",
        catalog_fingerprint="a" * 64,
        member=RotationMemberIdentity(
            workspace_id="workspace-1",
            workspace_account_id="workspace-account-1",
            preset_id="outgoing",
            email="outgoing@example.com",
            user_id="user-Outgoing",
        ),
    )


class Reads:
    def __init__(self):
        self.observed_at = NOW
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

    async def catalog(self):
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
                            preset_id="outgoing",
                            display_name="Outgoing",
                            email="outgoing@example.com",
                            user_id="user-Outgoing",
                        )
                    ],
                )
            ],
        )

    async def observe_membership(self, workspace_id: str):
        return MembershipObservation(
            schema_version=1,
            available=True,
            code="ok",
            workspace_id=workspace_id,
            workspace_account_id="workspace-account-1",
            catalog_fingerprint="a" * 64,
            observed_at=self.observed_at,
            complete=True,
            owner_verified=True,
            identity_ambiguous=False,
            partial_identity=False,
            duplicate_identity=False,
            unknown_member=False,
            members=self.members,
        )


def binding(**updates) -> WorkspaceMemberAccountBinding:
    values: dict[str, object] = {
        "workspace_id": "workspace-1",
        "workspace_account_id": "workspace-account-1",
        "preset_id": "outgoing",
        "member_user_id": "user-Outgoing",
        "member_email_normalized": "outgoing@example.com",
        "role": "member",
        "opencodex_account_id": "acct-outgoing",
        "established_at": NOW - timedelta(days=1),
    }
    values.update(updates)
    return WorkspaceMemberAccountBinding.model_validate(values)


class Bindings:
    def __init__(self, value=None):
        self.value = binding() if value is None else value
        self.calls = []

    async def get_exact(self, **kwargs):
        self.calls.append(kwargs)
        return self.value


def account_state(**updates) -> OpenCodexAccountState:
    values = {
        "schemaVersion": 1,
        "provider": "openai",
        "accountId": "acct-outgoing",
        "isMain": False,
        "credentialGeneration": 9,
        "observedAt": NOW_MS,
        "hasCredential": True,
        "needsReauth": False,
        "paused": False,
        "healthStatus": "healthy",
        "selectionState": "excluded",
        "exclusionReasons": ["quota_exhausted"],
        "quotaState": "exhausted",
        "quotaObservedAt": NOW_MS,
        "quotaWindows": [
            {
                "name": "weekly",
                "usedPercent": 100.0,
                "resetAt": NOW_MS + 86_400_000,
                "observedAt": NOW_MS,
            }
        ],
        "resetCreditState": {"availableCount": 0},
        "cooldowns": [],
        "stateRevision": "b" * 64,
    }
    values.update(updates)
    return OpenCodexAccountState.model_validate(values)


class Accounts:
    def __init__(self, value=None, error=None, values=None):
        self.value = account_state() if value is None else value
        self.error = error
        self.values = list(values or [])
        self.calls = []

    async def get(self, account_id: str):
        self.calls.append(account_id)
        if self.error:
            raise self.error
        if self.values:
            index = min(len(self.calls) - 1, len(self.values) - 1)
            return self.values[index]
        return self.value


class Budget:
    def __init__(self, admitted=True, code="admitted"):
        self.admitted = admitted
        self.code = code
        self.calls = []

    async def reserve(self, **kwargs):
        self.calls.append(kwargs)
        return MembershipMutationBudgetDecision(
            admitted=self.admitted,
            code=self.code,
            count_24h=1 if self.admitted else 3,
            count_168h=1 if self.admitted else 7,
            coverage_started_at=NOW - timedelta(days=8),
        )


def service(*, reads=None, bindings=None, accounts=None, budget=None):
    return WorkspaceMemberRotationDecisionService(
        reads or Reads(),
        bindings or Bindings(),
        accounts or Accounts(),
        budget or Budget(),
        clock=lambda: NOW,
    )


async def test_exhausted_exact_account_with_no_reset_credit_reserves_controller_budget():
    budget = Budget()
    decision = await service(budget=budget).evaluate(request())

    assert decision.state == "admission_ready"
    assert decision.admission_ready is True
    assert decision.attention_required is False
    assert decision.binding is not None and decision.binding.opencodex_account_id == "acct-outgoing"
    assert decision.account_evidence is not None
    assert decision.account_evidence.credential_generation == 9
    assert decision.account_evidence.state_revision == "b" * 64
    assert decision.account_evidence.reset_credit_available_count == 0
    assert len(budget.calls) == 1
    assert budget.calls[0] == {
        "operation_id": "budget-1",
        "evaluation_id": "evaluation-1",
        "workspace_id": "workspace-1",
        "workspace_account_id": "workspace-account-1",
    }


@pytest.mark.parametrize(
    ("state", "expected", "attention"),
    [
        (
            account_state(quotaState="available", selectionState="selectable", exclusionReasons=[]),
            "quota_available",
            False,
        ),
        (account_state(quotaState="unknown", quotaObservedAt=None), "quota_unknown", True),
        (
            account_state(observedAt=NOW_MS - 31_000, quotaObservedAt=NOW_MS - 31_000),
            "account_state_stale",
            True,
        ),
        (account_state(resetCreditState=None), "reset_credit_unknown", True),
        (account_state(resetCreditState={"availableCount": 1}), "reset_required", False),
        (account_state(needsReauth=True, exclusionReasons=["needs_reauth"]), "account_state_blocked", True),
    ],
)
async def test_non_admissible_account_states_do_not_reserve_membership_budget(state, expected, attention):
    budget = Budget()
    decision = await service(accounts=Accounts(state), budget=budget).evaluate(request())
    assert decision.state == expected
    assert decision.attention_required is attention
    assert decision.admission_ready is False
    assert budget.calls == []


async def test_missing_binding_and_account_state_failure_fail_closed_without_budget_reservation():
    missing = Bindings(value=False)
    missing.value = None
    budget = Budget()
    decision = await service(bindings=missing, budget=budget).evaluate(request())
    assert decision.state == "account_binding_missing"
    assert decision.attention_required is True
    assert budget.calls == []

    unavailable = await service(
        accounts=Accounts(error=OpenCodexAccountStateError("opencodex_account_state_unavailable")),
        budget=budget,
    ).evaluate(request())
    assert unavailable.state == "account_state_unavailable"
    assert budget.calls == []


async def test_rotation_rejects_unstable_account_projection_before_budget_reservation():
    budget = Budget()
    accounts = Accounts(
        values=[
            account_state(stateRevision="b" * 64),
            account_state(stateRevision="c" * 64),
        ]
    )
    decision = await service(accounts=accounts, budget=budget).evaluate(request())
    assert decision.state == "account_state_unstable"
    assert decision.attention_required is True
    assert decision.admission_ready is False
    assert accounts.calls == ["acct-outgoing", "acct-outgoing"]
    assert budget.calls == []


async def test_rotation_uses_exact_binding_not_email_or_selector_fallback():
    wrong = Bindings(binding(opencodex_account_id="acct-other", member_user_id="user-Different"))
    accounts = Accounts()
    with pytest.raises(RotationDecisionError, match="rotation_account_binding_identity_mismatch"):
        await service(bindings=wrong, accounts=accounts).evaluate(request())
    assert accounts.calls == []


async def test_stale_or_changed_workspace_member_blocks_before_account_lookup():
    reads = Reads()
    reads.observed_at = NOW - timedelta(seconds=31)
    accounts = Accounts()
    with pytest.raises(RotationDecisionError, match="rotation_membership_observation_expired"):
        await service(reads=reads, accounts=accounts).evaluate(request())
    assert accounts.calls == []

    reads = Reads()
    reads.members = [member for member in reads.members if member.classification == "owner"]
    accounts = Accounts()
    with pytest.raises(RotationDecisionError, match="rotation_current_member_mismatch"):
        await service(reads=reads, accounts=accounts).evaluate(request())
    assert accounts.calls == []


async def test_membership_budget_block_is_controller_policy_not_opencodex_routing_state():
    budget = Budget(admitted=False, code="rolling_168h_limit")
    decision = await service(budget=budget).evaluate(request())
    assert decision.state == "mutation_budget_blocked"
    assert decision.budget is not None and decision.budget.code == "rolling_168h_limit"
    assert decision.account_evidence is not None and decision.account_evidence.quota_state == "exhausted"


async def test_revalidation_requires_same_generation_revision_and_exhausted_no_credit_state():
    accounts = Accounts()
    svc = service(accounts=accounts)
    decision = await svc.evaluate(request())
    evidence = decision.account_evidence
    assert evidence is not None

    await svc.revalidate_account_evidence(evidence)

    accounts.value = account_state(credentialGeneration=10, stateRevision="c" * 64)
    with pytest.raises(RotationDecisionError, match="rotation_account_evidence_changed"):
        await svc.revalidate_account_evidence(evidence)

    accounts.value = account_state(
        quotaState="available",
        selectionState="selectable",
        exclusionReasons=[],
        stateRevision="b" * 64,
    )
    changed = evidence.model_copy(update={"quota_state": "available"})
    with pytest.raises(RotationDecisionError, match="rotation_account_preconditions_changed"):
        await svc.revalidate_account_evidence(changed)


async def test_revalidation_rejects_transition_between_adjacent_projection_reads():
    stable = account_state(stateRevision="b" * 64)
    accounts = Accounts(value=stable)
    svc = service(accounts=accounts)
    decision = await svc.evaluate(request())
    evidence = decision.account_evidence
    assert evidence is not None

    accounts.values = [
        account_state(stateRevision="b" * 64),
        account_state(stateRevision="c" * 64),
    ]
    accounts.calls.clear()
    with pytest.raises(RotationDecisionError, match="rotation_account_state_unstable"):
        await svc.revalidate_account_evidence(evidence)


async def test_quota_freshness_is_independent_of_projection_capture_time():
    state = account_state(quotaObservedAt=NOW_MS - 181_000)
    budget = Budget()
    decision = await service(accounts=Accounts(state), budget=budget).evaluate(request())
    assert decision.state == "quota_unknown"
    assert budget.calls == []


async def test_rotation_uses_opencodex_normalized_quota_state_not_raw_window_percentage():
    budget = Budget()
    exhausted = account_state(
        quotaState="exhausted",
        quotaWindows=[{"name": "weekly", "usedPercent": 1.0, "observedAt": NOW_MS}],
    )
    ready = await service(accounts=Accounts(exhausted), budget=budget).evaluate(request())
    assert ready.state == "admission_ready"
    assert len(budget.calls) == 1

    budget = Budget()
    available = account_state(
        quotaState="available",
        selectionState="selectable",
        exclusionReasons=[],
        quotaWindows=[{"name": "weekly", "usedPercent": 100.0, "observedAt": NOW_MS}],
    )
    not_ready = await service(accounts=Accounts(available), budget=budget).evaluate(request())
    assert not_ready.state == "quota_available"
    assert budget.calls == []


async def test_exact_account_projection_identity_mismatch_fails_closed():
    accounts = Accounts(account_state(accountId="acct-other"))
    with pytest.raises(RotationDecisionError, match="rotation_account_state_identity_mismatch"):
        await service(accounts=accounts).evaluate(request())
