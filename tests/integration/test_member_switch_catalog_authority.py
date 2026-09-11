from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

import app.dependencies as dependencies
from app.modules.member_auth_handoff.catalog import PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG, MemberAuthHandoffCatalog
from app.modules.member_switch.repository import MemberSwitchControlRepository
from tests.integration.test_member_switch_participants import ROOT, prepare
from tests.integration.test_member_switch_participants import integration as integration

pytestmark = pytest.mark.integration


async def test_managed_lifecycle_uses_current_catalog_without_rewriting_legacy(integration, monkeypatch):
    monkeypatch.setattr(dependencies, "PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG", PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG)
    path = dependencies.get_settings().data_dir / "member-auth-handoff-catalog.json"
    before = b'{"schemaVersion": 1, "members": []}\n'
    path.write_bytes(before)
    assert integration.catalog.fingerprint() != PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG.fingerprint()
    run = await prepare(integration)
    assert run["phase"] == "auth_prepared"
    assert len(integration.oauth.starts) == 1
    await integration.verify_incoming()
    run = await integration.command(run, "advance_auth")
    run = await integration.command(run, "finish")
    assert run["phase"] == "completed"
    assert path.read_bytes() == before


async def test_catalog_drift_before_auth_prepare_has_no_local_or_external_effect(integration):
    run = await integration.create()
    for action in ("start", "observe_membership", "prepare_session"):
        run = await integration.command(run, action)
    current = integration.wire.examples["catalog"]
    current["workspaces"][0]["members"][0]["userId"] = "user-NewIdentity"
    changed = MemberAuthHandoffCatalog(
        (replace(integration.catalog.entries[0], user_id="user-NewIdentity"), *integration.catalog.entries[1:])
    )
    current["catalogFingerprint"] = changed.fingerprint()
    response = await integration.command(run, "prepare_auth", expected=409)
    assert response["error"]["code"] == "auth_catalog_identity_mismatch"
    assert (await integration.read(run))["revision"] == run["revision"]
    assert integration.oauth.starts == []
    assert (await integration.account("outgoing")).deactivation_reason is None


async def test_fingerprint_cannot_describe_different_catalog_entries(integration):
    # Both old validator and UI receive the claimed hash; only canonical recomputation
    # can reject the inconsistent extra entry before the first durable run write.
    current = integration.wire.examples["catalog"]
    extra = dict(current["workspaces"][0]["members"][0])
    extra.update(presetId="cdp-1-extra", email="extra@example.com", userId="user-Extra")
    current["workspaces"][0]["members"].append(extra)
    target = integration.catalog.entries[0]
    response = await integration.client.post(
        ROOT,
        json={
            "runId": str(uuid4()),
            "workspaceId": target.workspace_id,
            "presetId": target.preset_id,
            "catalogFingerprint": integration.catalog.fingerprint(),
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "auth_catalog_fingerprint_mismatch"
    assert (await MemberSwitchControlRepository(integration.sessions).admission_snapshot()).records == ()
    assert all(method == "GET" for method, _, _ in integration.wire.calls)
