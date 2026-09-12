"""Exercise real enrollment admission and child storage; only peers are synthetic."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.modules.member_auth_handoff.durable import HandoffEnvelope
from app.modules.member_switch.repository import MemberSwitchControlRepository
from tests.integration.test_member_switch_participants import ROOT
from tests.integration.test_member_switch_participants import integration as integration

pytestmark = pytest.mark.integration


async def prepare_enrollment(integration, monkeypatch):
    wire = integration.wire
    original = wire.response
    target = integration.catalog.entries[0]

    def response(method, path, body):
        if method == "POST" and path == f"/workspaces/{target.workspace_id}/observe":
            # Use the production HTTP adapter/schema, with no live workspace.
            class Observation:
                status = 200

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def json(self):
                    return {
                        "schemaVersion": 1,
                        "available": True,
                        "code": "ok",
                        "workspaceId": target.workspace_id,
                        "workspaceAccountId": target.workspace_account_id,
                        "catalogFingerprint": integration.catalog.fingerprint(),
                        "observedAt": datetime.now(timezone.utc).isoformat(),
                        "complete": True,
                        "ownerVerified": True,
                        "identityAmbiguous": False,
                        "partialIdentity": False,
                        "duplicateIdentity": False,
                        "unknownMember": False,
                        "members": [{"email": target.email, "userId": target.user_id, "classification": "managed"}],
                    }

            return Observation()
        if method == "POST" and path == "/oauth-enrollment-browser/open":
            class EgoBrowser:
                status = 200

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def json(self):
                    return {
                        "accepted": True,
                        "state": "user_controlled",
                        "code": "ego_task_space_handed_off",
                        "enrollmentId": body["enrollmentId"],
                        "profileId": "CodexLB-account-synthetic",
                        "taskSpaceId": 17,
                        "ownership": "agentDelegatedToUser",
                        "outcomeUnknown": False,
                    }

            return EgoBrowser()
        if method == "POST" and path == "/oauth-enrollment-browser/profile-status":
            class EgoProfile:
                status = 200

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def json(self):
                    return {
                        "ready": True,
                        "code": "ego_profile_ready",
                        "profileId": "CodexLB-account-synthetic",
                    }

            return EgoProfile()
        return original(method, path, body)

    monkeypatch.setattr(wire, "response", response)
    created = await integration.client.post(
        ROOT + "/oauth-enrollments",
        json={
            "enrollmentId": str(uuid4()),
            "workspaceId": target.workspace_id,
            "presetId": target.preset_id,
            "memberEmail": target.email,
            "memberUserId": target.user_id,
            "catalogFingerprint": integration.catalog.fingerprint(),
        },
    )
    assert created.status_code == 200, created.text
    prepared = await enrollment_command(integration, created.json(), "prepare_auth")
    assert prepared.status_code == 200, prepared.text
    view = prepared.json()
    child = await MemberSwitchControlRepository(integration.sessions).get("handoff:" + view["handoffId"])
    assert child is not None and child.pending_action is None
    assert HandoffEnvelope.model_validate_json(child.payload).handoff.state == "device_code_issued"
    opened = await enrollment_command(integration, view, "open_auth_browser")
    assert opened.status_code == 200, opened.text
    result = opened.json()
    assert result["phase"] == "auth_browser_opened"
    assert result["browserProfileId"] == "CodexLB-account-synthetic"
    return result


async def enrollment_command(integration, view, action, command_id=None):
    return await integration.client.post(
        f"{ROOT}/oauth-enrollments/{view['id']}/commands",
        json={"action": action, "expectedRevision": view["revision"], "commandId": command_id or str(uuid4())},
    )


@pytest.mark.parametrize("outcome", ["pending", "success", "error"])
async def test_own_durable_child_can_advance_without_admitting_other_work(integration, monkeypatch, outcome):
    view = await prepare_enrollment(integration, monkeypatch)
    if outcome == "success":
        await integration.verify_incoming()
    else:
        integration.oauth.status = outcome
    command_id = str(uuid4())
    response = await enrollment_command(integration, view, "advance_auth", command_id)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (
        result["phase"]
        == {"pending": "auth_browser_opened", "success": "auth_confirmed", "error": "needs_attention"}[outcome]
    )
    assert integration.oauth.observations == ["synthetic-oauth"]
    duplicate = await enrollment_command(integration, view, "advance_auth", command_id)
    assert duplicate.status_code == 200 and duplicate.json() == result
    assert integration.oauth.observations == ["synthetic-oauth"]
    admission = (await integration.client.get(ROOT + "/admission")).json()
    assert admission["canCreate"] is False
    if outcome != "pending":
        finished = await enrollment_command(integration, result, "finish")
        assert finished.status_code == 200, finished.text
        assert finished.json()["phase"] == "completed"
        assert (await integration.client.get(ROOT + "/admission")).json()["canCreate"] is True
    assert len(integration.oauth.starts) == 1
    old = await integration.account("outgoing")
    assert old is not None and old.status.value == "active" and old.deactivation_reason is None
    assert not any(path in {"/operations", "/participant-commands"} for _, path, _ in integration.wire.calls)


@pytest.mark.parametrize("mismatch", ["pending", "parent", "handoff", "identity", "preserve"])
async def test_foreign_or_uncertain_handoff_still_blocks_enrollment(integration, monkeypatch, mismatch):
    view = await prepare_enrollment(integration, monkeypatch)
    controls = MemberSwitchControlRepository(integration.sessions)
    child = await controls.get("handoff:" + view["handoffId"])
    assert child is not None
    envelope = HandoffEnvelope.model_validate_json(child.payload)
    if mismatch == "pending":
        await controls.claim(child, str(uuid4()), "advance_auth", "synthetic-pending", expected_revision=child.revision)
    else:
        if mismatch == "parent":
            envelope.managed_run_id = str(uuid4())
        elif mismatch == "handoff":
            envelope.handoff.handoff_id = str(uuid4())
        elif mismatch == "identity":
            envelope.handoff.request.target_user_id = "user-Different"
        else:
            envelope.handoff.request.preserve_other_auth = False
        await controls.save(child, envelope.model_dump_json(), complete=True)
    before = await controls.get(view["id"])
    response = await enrollment_command(integration, view, "advance_auth")
    assert response.status_code == 409, response.text
    assert await controls.get(view["id"]) == before
    assert integration.oauth.observations == []
